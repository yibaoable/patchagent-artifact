import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile

from pathlib import Path
from typing import Optional

from nvwa.dataset_container import running_inside_dataset_container
from nvwa.parser.sanitizer import Sanitizer
from skyset.skyset_tools.secb_loader import SecbDatasetLoader


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    return process.returncode, process.stdout, process.stderr


def _run_local_command(cmd: str, cwd: Optional[str] = None) -> tuple[int, str, str]:
    process = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return process.returncode, process.stdout, process.stderr


def _docker_exec(container: str, work_dir: str, cmd: str) -> tuple[int, str, str]:
    return _run_command(
        [
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            f"cd {shlex.quote(work_dir)} && {cmd}",
        ]
    )


def _docker_exec_root(container: str, cmd: str) -> tuple[int, str, str]:
    return _run_command(
        [
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            cmd,
        ]
    )


def _docker_cp_to_container(local_path: str, container: str, container_path: str) -> tuple[int, str, str]:
    return _run_command(["docker", "cp", local_path, f"{container}:{container_path}"])


def _normalize_sanitizer(sanitizer: Optional[str | Sanitizer]) -> str:
    if sanitizer is None:
        return ""
    if isinstance(sanitizer, Sanitizer):
        sanitizer = sanitizer.value
    return str(sanitizer).strip().lower()


def _failure_keywords(sanitizer: Optional[str | Sanitizer]) -> list[str]:
    generic = [
        "runtime error:",
        "ERROR: AddressSanitizer",
        "AddressSanitizer:DEADLYSIGNAL",
        "SEGV on unknown address",
        "SUMMARY: AddressSanitizer",
        "SUMMARY: UndefinedBehaviorSanitizer",
        "UndefinedBehaviorSanitizer",
    ]
    sanitizer_name = _normalize_sanitizer(sanitizer)
    if sanitizer_name in {"address", "asan", "addresssanitizer"}:
        return generic
    if sanitizer_name in {"undefined", "ubsan", "undefinedbehaviorsanitizer"}:
        return generic
    return generic


def _format_step(name: str, rc: int, stdout: str, stderr: str) -> str:
    return (
        f"=========={name} rc={rc}===========\n"
        f"stdout:\n{stdout or '<empty>'}\n"
        f"stderr:\n{stderr or '<empty>'}\n"
        f"===================================\n"
    )


def _append_failed_step(logs: list[str], name: str, rc: int, stdout: str, stderr: str) -> None:
    if rc != 0:
        logs.append(_format_step(name, rc, stdout, stderr))


def _append_step(logs: list[str], name: str, rc: int, stdout: str, stderr: str) -> None:
    logs.append(_format_step(name, rc, stdout, stderr))


def _format_note(name: str, lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line)
    return (
        f"=========={name}===========\n"
        f"{body or '<empty>'}\n"
        f"===================================\n"
    )


def _normalize_expected_exit_code(expected_exit_code: Optional[int]) -> int:
    try:
        return int(expected_exit_code if expected_exit_code is not None else 0)
    except (TypeError, ValueError):
        return 0


def _runtime_container_source(setup_log: str) -> str:
    if "docker run rc=0" in setup_log:
        return "created"
    if "docker start rc=0" in setup_log or "inspect container rc=0" in setup_log or "inspect running rc=0" in setup_log:
        return "reused"
    return "unknown"


def _repo_changes_apply_command(repo_changes_path: str = "/testcase/repo_changes.diff") -> str:
    quoted = shlex.quote(repo_changes_path)
    return "\n".join(
        [
            f"if [[ -f {quoted} ]]; then",
            f"    if ! git apply --check {quoted} &>/dev/null; then",
            '        echo "Repository changes already applied or cannot be applied cleanly. Proceeding with patch."',
            "    else",
            '        echo "Applying repository changes from repo_changes.diff..."',
            f"        git apply {quoted} || echo \"Warning: Could not apply repo_changes.diff cleanly. Proceeding anyway.\"",
            "    fi",
            "fi",
        ]
    )


def _build_repro_failure_stderr(
    stderr: str,
    *,
    expected_exit_code: int,
    actual_exit_code: int,
    matched_failure_keywords: bool,
) -> str:
    details = [stderr or ""]
    if matched_failure_keywords:
        details.append("matched_failure_keywords=true")
    details.append(f"expected_exit_code={expected_exit_code}")
    details.append(f"actual_exit_code={actual_exit_code}")
    return "\n".join(item for item in details if item)


def _secbench_repro_succeeded(
    actual_exit_code: int,
    expected_exit_code: int,
    matched_failure_keywords: bool,
) -> bool:
    return not matched_failure_keywords and (
        actual_exit_code == 0 or actual_exit_code == expected_exit_code
    )


def _append_secbench_validate_context(
    logs: list[str],
    *,
    mode: str,
    validate_dir: str,
    work_dir: str,
    expected_exit_code: int,
    runtime_container: Optional[str] = None,
    runtime_container_source: Optional[str] = None,
) -> None:
    lines = [
        f"mode={mode}",
        f"work_dir={work_dir}",
        f"validate_dir={validate_dir}",
        f"expected_exit_code={expected_exit_code}",
        "workspace_reset=git reset --hard && git clean -xdf before validate",
        "mount_note=mounted source changes are visible in the container, but uncommitted changes in validate_dir are discarded before patching",
    ]
    if runtime_container:
        lines.append(f"runtime_container={runtime_container}")
    if runtime_container_source:
        lines.append(f"runtime_container_source={runtime_container_source}")
    logs.append(_format_note("secbench validate context", lines))


def _runtime_container_name(instance_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", instance_id).strip("-.").lower()
    prefix = os.getenv("SECBENCH_RUNTIME_CONTAINER_PREFIX", "secbench")
    return f"{prefix}-{sanitized}" if prefix else sanitized


def _looks_like_image_reference(ref: str) -> bool:
    return "/" in ref or "@" in ref or ":" in ref


def _docker_container_exists(container: str) -> tuple[bool, str]:
    rc, out, err = _run_command(["docker", "inspect", "--type=container", container])
    return rc == 0, _format_step("inspect container", rc, out, err)


def _docker_image_exists(image: str) -> tuple[bool, str]:
    rc, out, err = _run_command(["docker", "inspect", "--type=image", image])
    return rc == 0, _format_step("inspect image", rc, out, err)


def _docker_container_running(container: str) -> tuple[bool, str]:
    rc, out, err = _run_command(["docker", "inspect", "-f", "{{.State.Running}}", container])
    return rc == 0 and out.strip().lower() == "true", _format_step("inspect running", rc, out, err)


def _docker_start(container: str) -> tuple[bool, str]:
    rc, out, err = _run_command(["docker", "start", container])
    return rc == 0, _format_step("docker start", rc, out, err)


def _docker_run_background(image: str, container: str, extra_mounts: list[str] | None = None) -> tuple[bool, str]:
    cwd = os.getcwd()
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "--entrypoint",
        "/bin/sh",
        "-w",
        cwd,
        "-v",
        f"{cwd}:{cwd}",
        "-v",
        "agent_venv:/opt/venv:ro",
        "-v",
        "agent_tools:/opt/tools:ro",
    ]
    if extra_mounts:
        args.extend(extra_mounts)
    args.extend([image, "-c", "while :; do sleep 3600; done"])

    rc, out, err = _run_command(args)
    return rc == 0, _format_step("docker run", rc, out, err)


def _install_llvm(container: str) -> str:
    rc, out, err = _run_command(
        [
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            "apt-get update && apt-get install -y llvm llvm-14 llvm-14-tools bear",
        ]
    )
    return _format_step("install runtime packages", rc, out, err)


def _ensure_existing_container(container: str) -> tuple[Optional[str], str]:
    logs: list[str] = []
    running, step_log = _docker_container_running(container)
    logs.append(step_log)
    if running:
        return container, "".join(logs)

    started, step_log = _docker_start(container)
    logs.append(step_log)
    if started:
        return container, "".join(logs)

    return None, "".join(logs)


def _ensure_exec_container(
    instance_id: str,
    container_name: str,
    work_dir: str = "",
    extra_mount_paths: Optional[list[str]] = None,
) -> tuple[Optional[str], str]:
    logs: list[str] = []
    extra_mounts: list[str] = []
    mounted_paths: list[str] = []
    if work_dir:
        mounted_paths.append(work_dir)
    if extra_mount_paths:
        mounted_paths.extend(extra_mount_paths)

    seen_mounts: set[str] = set()
    for path in mounted_paths:
        if not path or path in seen_mounts:
            continue
        extra_mounts.extend(["-v", f"{path}:{path}"])
        seen_mounts.add(path)

    if _looks_like_image_reference(container_name):
        image_exists, _ = _docker_image_exists(container_name)
        if not image_exists:
            return None, "".join(logs)
    else:
        exists, step_log = _docker_container_exists(container_name)
        logs.append(step_log)
        if exists:
            container, extra_log = _ensure_existing_container(container_name)
            logs.append(extra_log)
            if container is not None:
                logs.append(_install_llvm(container))
            return container, "".join(logs)

        image_exists, _ = _docker_image_exists(container_name)
        if not image_exists:
            return None, "".join(logs)

    runtime_container = _runtime_container_name(instance_id)
    exists, step_log = _docker_container_exists(runtime_container)
    logs.append(step_log)
    if exists:
        container, extra_log = _ensure_existing_container(runtime_container)
        logs.append(extra_log)
        if container is not None:
            logs.append(_install_llvm(container))
        return container, "".join(logs)

    created, step_log = _docker_run_background(container_name, runtime_container, extra_mounts=extra_mounts)
    logs.append(step_log)
    if created:
        logs.append(_install_llvm(runtime_container))
        return runtime_container, "".join(logs)
    return None, "".join(logs)


def prepare_secbench_immutable_dir(
    instance_id: str,
    source_dir: str,
    immutable_dir: str,
    container_name: str = "",
    work_dir: str = "",
) -> tuple[bool, str]:
    logs: list[str] = []

    try:
        if os.path.exists(immutable_dir):
            shutil.rmtree(immutable_dir)
        os.makedirs(os.path.dirname(immutable_dir) or "/", exist_ok=True)
        shutil.copytree(source_dir, immutable_dir)
        copied_compile_commands = os.path.join(immutable_dir, "compile_commands.json")
        if os.path.exists(copied_compile_commands):
            os.unlink(copied_compile_commands)
    except OSError as exc:
        return False, _format_step("prepare immutable dir", 1, "", str(exc))

    build_cmd = "bear secb build"
    build_rc = 0
    build_out = ""
    build_err = ""
    if running_inside_dataset_container():
        build_rc, build_out, build_err = _run_local_command(build_cmd, cwd=immutable_dir)
    else:
        exec_container, setup_log = _ensure_exec_container(
            instance_id,
            container_name,
            "",
            extra_mount_paths=[immutable_dir],
        )
        if setup_log:
            logs.append(setup_log)
        if exec_container is None:
            return False, "".join(logs)
        build_rc, build_out, build_err = _docker_exec(exec_container, immutable_dir, build_cmd)

    compile_commands_path = os.path.join(immutable_dir, "compile_commands.json")
    if _path_exists(compile_commands_path):
        return True, "".join(logs)

    _append_failed_step(logs, "bear secb build", build_rc, build_out, build_err)

    source_compile_commands = _secb_compile_commands_source(instance_id)
    if not _path_exists(source_compile_commands):
        logs.append(
            _format_step(
                "compile_commands.json",
                1,
                "",
                f"missing: {compile_commands_path}; fallback source missing: {source_compile_commands}",
            )
        )
        return False, "".join(logs)

    try:
        shutil.copyfile(source_compile_commands, compile_commands_path)
    except OSError as exc:
        logs.append(_format_step("copy compile_commands", 1, "", str(exc)))
        return False, "".join(logs)

    rewrite_ok, rewrite_log = _rewrite_compile_commands_paths(
        compile_commands_path,
        [source_dir, work_dir],
        immutable_dir,
    )
    if rewrite_log:
        logs.append(rewrite_log)
    if not rewrite_ok:
        return False, "".join(logs)
    return True, "".join(logs)


def _secb_compile_commands_source(instance_id: str) -> str:
    root = os.getenv("SECBENCH_COMPILE_COMMANDS_ROOT", "/opt/tools/secb_compile_command_json")
    return os.path.join(root, instance_id, "compile_commands.json")


def _rewrite_prefixed_path(path: str, old_root: str, new_root: str) -> str:
    normalized_old = os.path.normpath(old_root)
    normalized_new = os.path.normpath(new_root)
    normalized_path = os.path.normpath(path)

    if normalized_path == normalized_old:
        return normalized_new

    prefix = normalized_old.rstrip(os.sep) + os.sep
    if normalized_path.startswith(prefix):
        return os.path.join(normalized_new, os.path.relpath(normalized_path, normalized_old))
    return path


def _rewrite_compile_commands_paths(
    compile_commands_path: str,
    source_roots: list[str],
    immutable_dir: str,
) -> tuple[bool, str]:
    try:
        with open(compile_commands_path, "r", encoding="utf-8") as f:
            commands = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return False, _format_step("rewrite compile_commands", 1, "", str(exc))

    if not isinstance(commands, list):
        return False, _format_step("rewrite compile_commands", 1, "", "compile_commands.json must contain a list")

    normalized_roots = [os.path.normpath(root) for root in source_roots if root]
    rewritten: list[dict] = []
    for entry in commands:
        if not isinstance(entry, dict):
            rewritten.append(entry)
            continue

        updated = dict(entry)
        directory = updated.get("directory")
        if isinstance(directory, str):
            for root in normalized_roots:
                directory = _rewrite_prefixed_path(directory, root, immutable_dir)
            updated["directory"] = directory

        file_path = updated.get("file")
        if isinstance(file_path, str):
            for root in normalized_roots:
                file_path = _rewrite_prefixed_path(file_path, root, immutable_dir)
            updated["file"] = file_path

        command = updated.get("command")
        if isinstance(command, str):
            for root in normalized_roots:
                command = command.replace(root, os.path.normpath(immutable_dir))
            updated["command"] = command

        arguments = updated.get("arguments")
        if isinstance(arguments, list):
            rewritten_args: list[str] = []
            for arg in arguments:
                if isinstance(arg, str):
                    for root in normalized_roots:
                        arg = arg.replace(root, os.path.normpath(immutable_dir))
                rewritten_args.append(arg)
            updated["arguments"] = rewritten_args

        rewritten.append(updated)

    try:
        with open(compile_commands_path, "w", encoding="utf-8") as f:
            json.dump(rewritten, f, indent=2)
            f.write("\n")
    except OSError as exc:
        return False, _format_step("rewrite compile_commands", 1, "", str(exc))
    return True, ""


def _prepare_docker_secbench_validate_dir(container: str, immutable_dir: str, validate_dir: str) -> tuple[bool, list[str]]:
    del immutable_dir
    logs: list[str] = []
    for name, cmd in (("git reset --hard", "git reset --hard"), ("git clean -xdf", "git clean -xdf")):
        rc, out, err = _docker_exec(container, validate_dir, cmd)
        _append_failed_step(logs, name, rc, out, err)
        if rc != 0:
            return False, logs
    return True, logs


def _path_exists(path: str) -> bool:
    return os.path.exists(path)


def _prepare_local_secbench_validate_dir(immutable_dir: str, validate_dir: str) -> tuple[bool, list[str]]:
    del immutable_dir
    logs: list[str] = []
    for name, cmd in (("git reset --hard", "git reset --hard"), ("git clean -xdf", "git clean -xdf")):
        rc, out, err = _run_local_command(cmd, cwd=validate_dir)
        _append_failed_step(logs, name, rc, out, err)
        if rc != 0:
            return False, logs
    return True, logs


def _validate_local_secbench_patch(
    immutable_dir: str,
    validate_dir: str,
    patch_text: str,
    sanitizer: Optional[str | Sanitizer] = None,
    expected_exit_code: Optional[int] = None,
) -> tuple[bool, str]:
    logs: list[str] = []
    normalized_expected_exit_code = _normalize_expected_exit_code(expected_exit_code)
    _append_secbench_validate_context(
        logs,
        mode="dataset-container-local",
        validate_dir=validate_dir,
        work_dir=immutable_dir,
        expected_exit_code=normalized_expected_exit_code,
    )
    ok, prep_logs = _prepare_local_secbench_validate_dir(immutable_dir, validate_dir)
    logs.extend(prep_logs)
    if not ok:
        return False, "".join(logs)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".diff") as patch_file:
        patch_file.write(patch_text)
        patch_path = patch_file.name

    try:
        rc, out, err = _run_local_command(_repo_changes_apply_command(), cwd=validate_dir)
        _append_failed_step(logs, "apply repo_changes.diff", rc, out, err)
        if rc != 0:
            return False, "".join(logs)

        rc, out, err = _run_local_command(f"git apply {shlex.quote(patch_path)}", cwd=validate_dir)
        _append_failed_step(logs, "apply model patch", rc, out, err)
        if rc != 0:
            return False, "".join(logs)

        rc, out, err = _run_local_command("secb build", cwd=validate_dir)
        _append_failed_step(logs, "secb build", rc, out, err)
        if rc != 0:
            return False, "".join(logs)

        rc, out, err = _run_local_command("secb repro", cwd=validate_dir)
        repro_text = f"{out or ''}\n{err or ''}"
        matched_failure_keywords = any(keyword in repro_text for keyword in _failure_keywords(sanitizer))
        if not _secbench_repro_succeeded(rc, normalized_expected_exit_code, matched_failure_keywords):
            logs.append(
                _format_step(
                    "secb repro",
                    rc,
                    out,
                    _build_repro_failure_stderr(
                        err,
                        expected_exit_code=normalized_expected_exit_code,
                        actual_exit_code=rc,
                        matched_failure_keywords=matched_failure_keywords,
                    ),
                )
            )
            return False, "".join(logs)
    finally:
        Path(patch_path).unlink(missing_ok=True)

    logs.append(
        _format_note(
            "secbench validate result",
            [
                "SUCCESS: Run Test passed",
                f"expected_exit_code={normalized_expected_exit_code}",
                f"actual_exit_code={rc}",
                f"matched_failure_keywords={str(matched_failure_keywords).lower()}",
                "success_rule=(actual_exit_code == 0 || actual_exit_code == expected_exit_code) && matched_failure_keywords == false",
            ],
        )
    )
    return True, "".join(logs)


def validate_secbench_patch_v2(
    instance_id: str,
    patch_text: str,
    container_name: str,
    work_dir: str,
    immutable_dir: Optional[str] = None,
    validate_dir: Optional[str] = None,
    sanitizer: Optional[str | Sanitizer] = None,
    patch_container_path: str = "/testcase/model_patch.diff",
    expected_exit_code: Optional[int] = None,
) -> tuple[bool, str]:
    del immutable_dir
    validate_dir = validate_dir or work_dir
    normalized_expected_exit_code = _normalize_expected_exit_code(expected_exit_code)

    if running_inside_dataset_container():
        return _validate_local_secbench_patch(
            immutable_dir=work_dir,
            validate_dir=validate_dir,
            patch_text=patch_text,
            sanitizer=sanitizer,
            expected_exit_code=normalized_expected_exit_code,
        )

    logs: list[str] = []
    exec_container, setup_log = _ensure_exec_container(instance_id, container_name, work_dir)
    if exec_container is None:
        if setup_log:
            logs.append(setup_log)
        return False, "".join(logs)
    if setup_log:
        logs.append(setup_log)

    _append_secbench_validate_context(
        logs,
        mode="host-runtime-container",
        validate_dir=validate_dir,
        work_dir=work_dir,
        expected_exit_code=normalized_expected_exit_code,
        runtime_container=exec_container,
        runtime_container_source=_runtime_container_source(setup_log),
    )

    ok, prep_logs = _prepare_docker_secbench_validate_dir(exec_container, work_dir, validate_dir)
    logs.extend(prep_logs)
    if not ok:
        return False, "".join(logs)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".diff") as patch_file:
        patch_file.write(patch_text)
        local_patch_path = patch_file.name

    try:
        rc, out, err = _docker_cp_to_container(local_patch_path, exec_container, patch_container_path)
        _append_failed_step(logs, "docker cp", rc, out, err)
        if rc != 0:
            return False, "".join(logs)
    finally:
        Path(local_patch_path).unlink(missing_ok=True)

    rc, out, err = _docker_exec(exec_container, validate_dir, _repo_changes_apply_command())
    _append_failed_step(logs, "apply repo_changes.diff", rc, out, err)
    if rc != 0:
        return False, "".join(logs)

    rc, out, err = _docker_exec(exec_container, validate_dir, f"git apply {shlex.quote(patch_container_path)}")
    _append_failed_step(logs, "apply model patch", rc, out, err)
    if rc != 0:
        return False, "".join(logs)

    rc, out, err = _docker_exec(exec_container, validate_dir, "secb build")
    _append_failed_step(logs, "secb build", rc, out, err)
    if rc != 0:
        return False, "".join(logs)

    rc, out, err = _docker_exec(exec_container, validate_dir, "secb repro")
    repro_text = f"{out or ''}\n{err or ''}"
    matched_failure_keywords = any(keyword in repro_text for keyword in _failure_keywords(sanitizer))
    if not _secbench_repro_succeeded(rc, normalized_expected_exit_code, matched_failure_keywords):
        logs.append(
            _format_step(
                "secb repro",
                rc,
                out,
                _build_repro_failure_stderr(
                    err,
                    expected_exit_code=normalized_expected_exit_code,
                    actual_exit_code=rc,
                    matched_failure_keywords=matched_failure_keywords,
                ),
            )
        )
        return False, "".join(logs)
    else:
        logs.append(
            _format_note(
                "secbench validate result",
                [
                    "SUCCESS: Run Test passed",
                    f"expected_exit_code={normalized_expected_exit_code}",
                    f"actual_exit_code={rc}",
                    f"matched_failure_keywords={str(matched_failure_keywords).lower()}",
                    "success_rule=(actual_exit_code == 0 || actual_exit_code == expected_exit_code) && matched_failure_keywords == false",
                ],
            )
        )
    return True, "".join(logs)


def validate_secbench_patch(
    instance_id: str,
    patch_text: str,
    dataset_path: Optional[str] = None,
) -> tuple[bool, str]:
    config = SecbDatasetLoader(dataset_path).get(instance_id)
    return validate_secbench_patch_v2(
        instance_id=config["instance_id"],
        patch_text=patch_text,
        container_name=config["container_name"],
        work_dir=config["work_dir"],
        sanitizer=config.get("sanitizer"),
        expected_exit_code=config.get("exit_code"),
    )
