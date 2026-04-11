import os
import shutil

from typing import Optional

from nvwa.dataset_container import running_inside_dataset_container
from nvwa.parser.base import SanitizerReport
from nvwa.parser.cwe import CWE
from nvwa.parser.sanitizer import Sanitizer
from nvwa.proxy.utils import revise_patch
from nvwa.sky.task import PatchTask, ROOT


def _normalize_sanitizer(raw: Optional[str | Sanitizer]) -> Sanitizer:
    if isinstance(raw, Sanitizer):
        return raw

    value = str(raw or "").strip().lower()
    mapping = {
        "address": Sanitizer.AddressSanitizer,
        "asan": Sanitizer.AddressSanitizer,
        "undefined": Sanitizer.UndefinedBehaviorSanitizer,
        "ubsan": Sanitizer.UndefinedBehaviorSanitizer,
        "jazzer": Sanitizer.JazzerSanitizer,
    }
    return mapping.get(value, Sanitizer.AddressSanitizer)


class DatasetPromptReport(SanitizerReport):
    def __init__(self, sanitizer: Sanitizer, content: str):
        super().__init__(sanitizer, content, CWE.UNKNOWN, [], {})

    @property
    def summary(self) -> str:
        return self.content

    def get_all_stacktrace(self):
        return []


class VulnFuncTask(PatchTask):
    dataset_name = ""
    dataset_label = "vulnerability"
    host_env_prefix = ""
    removed_source_paths: tuple[str, ...] = ()

    def __init__(
        self,
        config: dict,
        dataset_path: Optional[str] = None,
        skip_setup: bool = False,
    ):
        self.config = dict(config)
        self.dataset_path = dataset_path
        self.dataset = self.dataset_name or str(self.config.get("dataset") or "")
        self.project = self.project_name(self.config)
        self.tag = self.case_id(self.config)
        self.sanitizer = _normalize_sanitizer(self.config.get("sanitizer"))
        self.input_mode = "vuln_func"
        self.effective_input_mode = "vuln_func"
        self.patch = None
        self.sanitizer_report = None
        self.language = str(self.config.get("language") or "").strip().lower() or "java"

        self.work_dir = self._work_dir(self.config)
        self.container_name = self._container_name(self.config)
        self.containerized_repair = running_inside_dataset_container()
        self.host_src_dir = "" if self.containerized_repair else self._resolve_host_src_dir()

        if not skip_setup:
            assert self.setup(), f"Failed to setup {self}"

    def __str__(self):
        return f"[{self.project}, {self.tag}]"

    @classmethod
    def case_id(cls, config: dict) -> str:
        raise NotImplementedError

    @classmethod
    def project_name(cls, config: dict) -> str:
        raise NotImplementedError

    @classmethod
    def from_dataset(cls, case_id: str, dataset_path: Optional[str] = None, **kwargs):
        raise NotImplementedError

    def _description(self) -> str:
        raise NotImplementedError

    def _locations(self) -> list[str]:
        raise NotImplementedError

    def _validate_patch(self, patch_text: str) -> tuple[bool, str]:
        raise NotImplementedError

    def _prepare_container_immutable(self) -> tuple[bool, str]:
        raise NotImplementedError

    def _work_dir(self, config: dict) -> str:
        return str(config["work_dir"])

    def _container_name(self, config: dict) -> str:
        return str(config["container_name"])

    @property
    def path(self) -> str:
        return os.path.join(ROOT, self.dataset, self.tag)

    @property
    def immutable_project_path(self) -> str:
        return os.path.join(self.path, "immutable")

    @property
    def validate_project_path(self) -> str:
        return os.path.join(self.path, "validate")

    @property
    def report(self) -> str:
        return self.issue_summary

    @property
    def issue_summary(self) -> str:
        assert self.sanitizer_report is not None
        return self.sanitizer_report.summary

    @property
    def issue_kind(self) -> str:
        return f"{self.dataset_label} vulnerability description"

    def _candidate_host_src_dirs(self) -> list[str]:
        candidates = []

        if self.config.get("host_src_dir"):
            candidates.append(str(self.config["host_src_dir"]))

        normalized_tag = self.tag.upper().replace(".", "_").replace("-", "_")
        specific_key = f"{self.host_env_prefix}_HOST_SRC_DIR_{normalized_tag}"
        if os.getenv(specific_key):
            candidates.append(os.getenv(specific_key, ""))

        generic_dir = os.getenv(f"{self.host_env_prefix}_HOST_SRC_DIR")
        if generic_dir:
            candidates.append(generic_dir)

        root_dir = os.getenv(f"{self.host_env_prefix}_HOST_SRC_ROOT")
        if root_dir:
            candidates.extend(
                [
                    os.path.join(root_dir, self.tag),
                    os.path.join(root_dir, self.project),
                ]
            )

        return [candidate for candidate in candidates if candidate]

    def _expand_host_src_candidate(self, candidate: str) -> list[str]:
        normalized = os.path.abspath(os.path.expanduser(candidate))
        expanded = []
        if os.path.isdir(normalized):
            for nested in (
                os.path.join(normalized, self.tag),
                os.path.join(normalized, self.project),
            ):
                if os.path.isdir(nested):
                    expanded.append(nested)
        expanded.append(normalized)
        return expanded

    def _resolve_host_src_dir(self) -> str:
        fallback = ""
        for candidate in self._candidate_host_src_dirs():
            for expanded in self._expand_host_src_candidate(candidate):
                if not fallback:
                    fallback = expanded
                if os.path.isdir(expanded):
                    return expanded
        return fallback

    def _prepare_immutable_copy(self) -> bool:
        if not self.host_src_dir or not os.path.isdir(self.host_src_dir):
            return False

        os.makedirs(self.path, exist_ok=True)
        if os.path.exists(self.immutable_project_path):
            shutil.rmtree(self.immutable_project_path)

        shutil.copytree(self.host_src_dir, self.immutable_project_path)

        for relative_path in self.removed_source_paths:
            target = os.path.join(self.immutable_project_path, relative_path)
            if os.path.isdir(target):
                shutil.rmtree(target)
            elif os.path.isfile(target):
                os.unlink(target)

        return True

    def _build_vuln_context(self) -> str:
        lines = [
            f"{self.dataset_label} vulnerability context:",
            f"- dataset: {self.dataset}",
            f"- instance_id: {self.tag}",
            f"- project: {self.project}",
        ]

        description = self._description().strip()
        if description:
            lines.extend(["", "Bug description:", description])

        locations = self._locations()
        if locations:
            lines.extend(["", "Likely vulnerable locations (start with these file ranges):"])
            lines.extend(f"- {location}" for location in locations)
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

    def setup(self) -> bool:
        os.makedirs(self.path, exist_ok=True)
        if self.containerized_repair:
            ok, message = self._prepare_container_immutable()
            if not ok:
                if message:
                    from nvwa.logger import log
                    log.error(message)
                return False
        else:
            if not self.host_src_dir or not os.path.isdir(self.host_src_dir):
                return False
            if not self._prepare_immutable_copy():
                return False
        self.sanitizer_report = DatasetPromptReport(self.sanitizer, self._build_vuln_context())
        return True

    def build(self, *args, **kwargs) -> tuple[bool, str]:
        return True, ""

    def test(self, *args, **kwargs) -> tuple[bool, str]:
        return False, f"{self.dataset_label} tasks validate patches through dataset-specific container commands"

    def test_functional(self, *args, **kwargs) -> dict:
        return {
            "result": "unknown",
            "returncode": -1,
            "stdout": "",
            "stderr": "",
        }

    def validate(self, patch_path: str) -> tuple[bool, str]:
        with open(patch_path, "r", encoding="utf-8") as f:
            patch_text = f.read()
        patch_text, _ = revise_patch(patch_text, self.immutable_project_path)

        ret, report = self._validate_patch(patch_text)
        if ret:
            self.patch = patch_text
        return ret, report
