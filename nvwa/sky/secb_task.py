import os
import re
import shutil
import subprocess

from typing import Optional, Union

from nvwa.dataset_container import running_inside_dataset_container
from nvwa.logger import log
from nvwa.parser import parse
from nvwa.parser.base import SanitizerReport
from nvwa.parser.cwe import CWE
from nvwa.parser.sanitizer import Sanitizer
from nvwa.proxy.utils import revise_patch
from nvwa.secb_runtime import prepare_secbench_immutable_dir, validate_secbench_patch_v2
from nvwa.sky.task import PatchTask, ROOT
from skyset.skyset_tools.secb_loader import SecbDatasetLoader

WITH_LOCATION_INSTRUCTION = os.getenv("WITH_LOCATION_INSTRUCTION", "false")

def _normalize_sanitizer(raw: Optional[str | Sanitizer]) -> Sanitizer:
    if isinstance(raw, Sanitizer):
        return raw

    value = str(raw or "").strip().lower()
    mapping = {
        "address": Sanitizer.AddressSanitizer,
        "asan": Sanitizer.AddressSanitizer,
        "addresssanitizer": Sanitizer.AddressSanitizer,
        "undefined": Sanitizer.UndefinedBehaviorSanitizer,
        "ubsan": Sanitizer.UndefinedBehaviorSanitizer,
        "undefinedbehaviorsanitizer": Sanitizer.UndefinedBehaviorSanitizer,
        "bear": Sanitizer.BearSanitizer,
        "bearsanitizer": Sanitizer.BearSanitizer,
        "undefined": Sanitizer.UndefinedBehaviorSanitizer,
    }
    return mapping.get(value, Sanitizer.AddressSanitizer)


def _normalize_input_mode(raw: Optional[str]) -> str:
    mode = str(raw or "auto").strip().lower()
    if mode not in {"auto", "sanitizer", "vuln_func"}:
        raise ValueError(f"Unsupported SEC-bench input mode: {raw}")
    return mode


class SecbPromptReport(SanitizerReport):
    def __init__(self, sanitizer: Sanitizer, content: str):
        super().__init__(sanitizer, content, CWE.UNKNOWN, [], {})

    @property
    def summary(self) -> str:
        return self.content

    def get_all_stacktrace(self):
        return []


class SecbTask(PatchTask):
    STACK_FRAME_PATTERN = re.compile(r"^(\s*#\d+\s+0x[\w\d]+\s+in\s+.+?)\s+(/[^:\s]+(?:/[^:\s]+)*):(\d+)(?::(\d+))?(\s*)$")
    SUMMARY_PATTERN = re.compile(r"^(SUMMARY:\s+AddressSanitizer:\s+\S+\s+)(/[^:\s]+(?:/[^:\s]+)*):(\d+)(?::(\d+))?(\s+in\s+.+)$")

    def __init__(
        self,
        config: dict,
        dataset_path: Optional[str] = None,
        input_mode: str = "auto",
        skip_setup: bool = False,
    ):
        self.config = dict(config)
        self.dataset_path = dataset_path
        self.dataset = str(self.config.get("dataset") or "secbench")
        self.instance_id = str(self.config["instance_id"])
        self.project_name = str(self.config["project_name"])
        self.project = self.project_name
        self.tag = self.instance_id
        self.sanitizer = _normalize_sanitizer(self.config.get("sanitizer"))
        self.input_mode = _normalize_input_mode(input_mode or self.config.get("input_mode") or os.getenv("SECBENCH_INPUT_MODE"))
        self.effective_input_mode = self.input_mode
        self.patch: Union[None, str] = None
        self.sanitizer_report: Union[None, SanitizerReport] = None
        self.language = str(self.config.get("language") or "").strip().lower() or "c"

        self.work_dir = str(self.config["work_dir"])
        self.container_name = str(self.config["container_name"])
        try:
            self.expected_exit_code = int(self.config.get("exit_code", 0) or 0)
        except (TypeError, ValueError):
            self.expected_exit_code = 0
        self.raw_sanitizer_report = str(self.config.get("sanitizer_report") or "")
        self.bug_description = str(self.config.get("bug_description") or "")
        self.vul_func = list(self.config.get("vul_func") or [])
        self.containerized_repair = running_inside_dataset_container()
        self.host_src_dir = "" if self.containerized_repair else self._resolve_host_src_dir()
        self.compile_commands_dir = self.immutable_project_path

        if not skip_setup:
            assert self.setup(), f"Failed to setup {self}"

    def __str__(self):
        return f"[{self.project}, {self.instance_id}]"

    @classmethod
    def from_dataset(
        cls,
        instance_id: str,
        dataset_path: Optional[str] = None,
        input_mode: str = "auto",
        **kwargs,
    ) -> "SecbTask":
        loader = SecbDatasetLoader(dataset_path)
        return cls(loader.get(instance_id), dataset_path=loader.dataset_path, input_mode=input_mode, **kwargs)

    @property
    def path(self) -> str:
        return os.path.join(ROOT, "secbench", self.instance_id)

    @property
    def immutable_project_path(self) -> str:
        return os.path.join(self.path, "immutable")

    @property
    def mutable_project_path(self) -> str:
        return os.path.join(self.path, "mutable")

    @property
    def report_path(self) -> str:
        return os.path.join(self.path, "report.txt")

    @property
    def report(self) -> str:
        if self.raw_sanitizer_report:
            return self.raw_sanitizer_report
        return self.issue_summary

    @property
    def issue_summary(self) -> str:
        assert self.sanitizer_report is not None
        return self.sanitizer_report.summary

    @property
    def issue_kind(self) -> str:
        if self.effective_input_mode == "sanitizer":
            return "sanitizer report"
        return "SEC-bench vulnerability description"

    def _resolve_host_src_dir(self) -> str:
        candidates = []

        for key in ("host_src_dir", "source_dir"):
            value = self.config.get(key)
            if value:
                candidates.append(value)

        env_key = f"SECBENCH_HOST_SRC_DIR_{self.instance_id.upper().replace('.', '_').replace('-', '_')}"
        if os.getenv(env_key):
            candidates.append(os.getenv(env_key))
        if os.getenv("SECBENCH_HOST_SRC_DIR"):
            candidates.append(os.getenv("SECBENCH_HOST_SRC_DIR"))

        if host_root := os.getenv("SECBENCH_HOST_SRC_ROOT"):
            candidates.extend(
                [
                    os.path.join(host_root, self.instance_id),
                    os.path.join(host_root, self.project_name),
                ]
            )

        candidates.append(os.path.join(self.path, "immutable"))

        def expand_candidate(candidate: str) -> list[str]:
            normalized = os.path.abspath(os.path.expanduser(str(candidate)))
            if normalized.endswith("compile_commands.json"):
                normalized = os.path.dirname(normalized)

            expanded = []
            if os.path.isdir(normalized):
                for nested in (
                    os.path.join(normalized, self.instance_id),
                    os.path.join(normalized, self.project_name),
                ):
                    if os.path.isdir(nested):
                        expanded.append(nested)
            expanded.append(normalized)
            return expanded

        fallback = ""
        for candidate in candidates:
            if not candidate:
                continue
            for normalized in expand_candidate(candidate):
                if not fallback:
                    fallback = normalized
                if os.path.isdir(normalized):
                    return normalized
        return fallback

    def _build_vuln_context(self) -> str:
        lines = [
            "SEC-bench vulnerability context:",
            f"- instance_id: {self.instance_id}",
            f"- project: {self.project_name}",
            f"- sanitizer: {self.sanitizer}",
        ]

        if self.config.get("base_commit"):
            lines.append(f"- base_commit: {self.config['base_commit']}")
        if self.config.get("CVE_ID"):
            lines.append(f"- CVE: {self.config['CVE_ID']}")
        if self.config.get("cwe_info"):
            lines.append(f"- CWE: {', '.join(sorted(self.config['cwe_info'].keys()))}")

        if self.bug_description:
            lines.extend(["", "Bug description:", self.bug_description.strip()])
        elif self.config.get("bug_report"):
            lines.extend(["", "Bug report:", str(self.config["bug_report"]).strip()])

        if self.vul_func and WITH_LOCATION_INSTRUCTION == "true":
            lines.extend(["", "Likely vulnerable locations (start with these file ranges):"])
            for item in self.vul_func:
                file_path = item.get("file_path", "<unknown>")
                start_line = item.get("start_line", "?")
                end_line = item.get("end_line", start_line)
                lines.append(f"- {file_path}:{start_line}-{end_line}")
        else:
            lines.extend(["", "No exact vulnerable line range was provided by the dataset."])

        lines.extend(
            [
                "",
                "There may be no sanitizer stack trace for this task.",
                "Use the listed files, line ranges, and bug description as the primary starting point.",
            ]
        )
        return "\n".join(lines)

    def _guess_relative_source_path(self, source_path: str) -> Optional[str]:
        normalized_source = os.path.normpath(source_path)
        normalized_root = os.path.normpath(self.immutable_project_path)

        if normalized_source.startswith(normalized_root + os.sep):
            return os.path.relpath(normalized_source, normalized_root)

        top_level_entries: list[str] = []
        try:
            top_level_entries = sorted(os.listdir(normalized_root), key=len, reverse=True)
        except OSError:
            top_level_entries = []

        for entry in top_level_entries:
            marker = f"{os.sep}{entry}{os.sep}"
            if marker in normalized_source:
                return os.path.join(entry, normalized_source.rsplit(marker, 1)[1])

        work_dir_name = os.path.basename(self.work_dir.rstrip("/"))
        if work_dir_name:
            marker = f"{os.sep}{work_dir_name}{os.sep}"
            if marker in normalized_source:
                return normalized_source.rsplit(marker, 1)[1]

        if f"{os.sep}src{os.sep}" in normalized_source:
            return os.path.join("src", normalized_source.rsplit(f"{os.sep}src{os.sep}", 1)[1])

        return None

    def _normalize_report_for_parser(self, report: str) -> str:
        def rewrite_stack_frame(line: str) -> str:
            match = self.STACK_FRAME_PATTERN.match(line)
            if match is None:
                return line

            prefix, source_path, line_no, column_no, suffix = match.groups()
            relative_path = self._guess_relative_source_path(source_path)
            if relative_path is None:
                return line

            location = f"/root/{relative_path}:{line_no}"
            if column_no is not None:
                location += f":{column_no}"
            return f"{prefix} {location}{suffix}"

        def rewrite_summary(line: str) -> str:
            match = self.SUMMARY_PATTERN.match(line)
            if match is None:
                return line

            prefix, source_path, line_no, column_no, suffix = match.groups()
            relative_path = self._guess_relative_source_path(source_path)
            if relative_path is None:
                return line

            location = f"/root/{relative_path}:{line_no}"
            if column_no is not None:
                location += f":{column_no}"
            return f"{prefix}{location}{suffix}"

        normalized_lines = []
        for line in report.splitlines():
            line = rewrite_stack_frame(line)
            line = rewrite_summary(line)
            normalized_lines.append(line)
        return "\n".join(normalized_lines)

    def _parse_sanitizer_report(self, report: str) -> Optional[SanitizerReport]:
        parsed = parse(report, self.sanitizer)
        if parsed is None:
            return None
        if len(parsed.stacktrace) == 0:
            return None
        return parsed

    def _build_prompt_report(self) -> SanitizerReport:
        if self.input_mode != "vuln_func" and self.raw_sanitizer_report:
            self.effective_input_mode = "sanitizer"
            parsed = self._parse_sanitizer_report(self.raw_sanitizer_report)
            if parsed is not None:
                return parsed

            normalized_report = self._normalize_report_for_parser(self.raw_sanitizer_report)
            parsed = self._parse_sanitizer_report(normalized_report)
            if parsed is not None:
                return parsed

            log.warning(f"{self} sanitizer report could not be parsed into a usable stacktrace; falling back to raw report text")
            return SecbPromptReport(self.sanitizer, normalized_report)

        if self.input_mode == "sanitizer":
            log.warning(f"{self} requested sanitizer mode but no sanitizer_report is available; falling back to vuln_func mode")

        self.effective_input_mode = "vuln_func"
        return SecbPromptReport(self.sanitizer, self._build_vuln_context())

    def _cleanup_host_src_dir(self) -> bool:
        git_dir = os.path.join(self.host_src_dir, ".git")
        if not os.path.isdir(git_dir):
            return True

        commands = (
            ["git", "reset", "--hard"],
            ["git", "clean", "-xdf", "-e", "compile_commands.json"],
        )
        for command in commands:
            result = subprocess.run(command, cwd=self.host_src_dir, capture_output=True, text=True)
            if result.returncode != 0:
                log.error(
                    f"{self} failed to clean host source directory with {' '.join(command)}\n"
                    f"stdout:\n{result.stdout or '<empty>'}\n"
                    f"stderr:\n{result.stderr or '<empty>'}"
                )
                return False
        return True

    def setup(self) -> bool:
        if not self.work_dir:
            log.error(f"{self} work_dir is missing")
            return False

        os.makedirs(self.path, exist_ok=True)

        if self.containerized_repair:
            if not os.path.isdir(self.work_dir):
                log.error(f"{self} immutable SEC-bench work_dir does not exist in container: {self.work_dir}")
                return False
            source_dir = self.work_dir
        else:
            if not self.host_src_dir or not os.path.isdir(self.host_src_dir):
                log.error(f"{self} host source directory does not exist: {self.host_src_dir}")
                return False

            if not self._cleanup_host_src_dir():
                return False
            source_dir = self.host_src_dir

        ok, report = prepare_secbench_immutable_dir(
            instance_id=self.instance_id,
            source_dir=source_dir,
            immutable_dir=self.immutable_project_path,
            container_name=self.container_name,
            work_dir=self.work_dir,
        )
        if not ok:
            if report:
                log.error(report)
            return False

        self.sanitizer_report = self._build_prompt_report()
        return True

    def build(self, *args, **kwargs) -> tuple[bool, str]:
        compile_commands = os.path.join(self.compile_commands_dir, "compile_commands.json")
        if os.path.exists(compile_commands):
            return True, ""
        return False, f"compile_commands.json not found: {compile_commands}"

    def test(self, *args, **kwargs) -> tuple[bool, str]:
        return False, "SEC-bench tasks validate patches through secb patch/build/repro"

    def test_functional(self, *args, **kwargs) -> dict:
        return {
            "result": "unknown",
            "returncode": -1,
            "stdout": "",
            "stderr": "",
        }

    def validate(self, patch_path: str) -> tuple[bool, str]:
        log.info(f"Validating {self} with {patch_path}")

        with open(patch_path, "r", encoding="utf-8") as f:
            patch_text = f.read()
        patch_text, _ = revise_patch(patch_text, self.immutable_project_path)

        ret, report = validate_secbench_patch_v2(
            instance_id=self.instance_id,
            patch_text=patch_text,
            container_name=self.container_name,
            work_dir=self.work_dir,
            immutable_dir=self.immutable_project_path,
            validate_dir=self.work_dir,
            sanitizer=self.sanitizer,
            expected_exit_code=self.expected_exit_code,
        )
        if ret:
            self.patch = patch_text
            log.info(f"Task {self} has been patched")
        return ret, report
