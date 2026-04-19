import os
import re
import shutil
import tempfile

from pathlib import Path
from typing import Optional

from nvwa.dataset_container import running_inside_dataset_container
from nvwa.secb_runtime import (
    _append_failed_step,
    _docker_container_exists,
    _docker_container_running,
    _docker_cp_to_container,
    _docker_exec,
    _docker_image_exists,
    _docker_run_background,
    _docker_start,
    _format_step,
    _looks_like_image_reference,
    _run_local_command,
)


def _runtime_container_name(instance_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", instance_id).strip("-.").lower()
    prefix = os.getenv("PATCHEVAL_RUNTIME_CONTAINER_PREFIX", "patcheval")
    return f"{prefix}-{sanitized}" if prefix else sanitized


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


def _ensure_exec_container(instance_id: str, container_name: str) -> tuple[Optional[str], str]:
    logs: list[str] = []

    if _looks_like_image_reference(container_name):
        image_exists, step_log = _docker_image_exists(container_name)
        logs.append(step_log)
        if not image_exists:
            return None, "".join(logs)
    else:
        exists, step_log = _docker_container_exists(container_name)
        logs.append(step_log)
        if exists:
            container, extra_log = _ensure_existing_container(container_name)
            logs.append(extra_log)
            return container, "".join(logs)
        image_exists, step_log = _docker_image_exists(container_name)
        logs.append(step_log)
        if not image_exists:
            return None, "".join(logs)

    runtime_container = _runtime_container_name(instance_id)
    exists, step_log = _docker_container_exists(runtime_container)
    logs.append(step_log)
    if exists:
        container, extra_log = _ensure_existing_container(runtime_container)
        logs.append(extra_log)
        return container, "".join(logs)

    created, step_log = _docker_run_background(container_name, runtime_container)
    logs.append(step_log)
    if created:
        return runtime_container, "".join(logs)
    return None, "".join(logs)


def prepare_patcheval_immutable_dir(instance_id: str, source_dir: str, immutable_dir: str) -> tuple[bool, str]:
    del instance_id
    try:
        if os.path.exists(immutable_dir):
            shutil.rmtree(immutable_dir)
        os.makedirs(os.path.dirname(immutable_dir) or "/", exist_ok=True)
        shutil.copytree(source_dir, immutable_dir)
    except OSError as exc:
        return False, _format_step("prepare immutable dir", 1, "", str(exc))
    return True, ""


def _prepare_local_patcheval_validate_dir(immutable_dir: str, validate_dir: str) -> tuple[bool, list[str]]:
    del immutable_dir
    logs: list[str] = []
    for name, cmd in (("git reset --hard", "git reset --hard"), ("git clean -xdf", "git clean -xdf")):
        rc, out, err = _run_local_command(cmd, cwd=validate_dir)
        _append_failed_step(logs, name, rc, out, err)
        if rc != 0:
            return False, logs
    return True, logs


def _prepare_docker_patcheval_validate_dir(container: str, immutable_dir: str, validate_dir: str) -> tuple[bool, list[str]]:
    del immutable_dir
    logs: list[str] = []
    for name, cmd in (("git reset --hard", "git reset --hard"), ("git clean -xdf", "git clean -xdf")):
        rc, out, err = _docker_exec(container, validate_dir, cmd)
        _append_failed_step(logs, name, rc, out, err)
        if rc != 0:
            return False, logs
    return True, logs


def _classify_patcheval_error(error_log: str, language: str) -> str:
    text = error_log or ""
    normalized_language = str(language or "").strip().lower()

    if "patch does not apply" in text or "error: corrupt patch at line" in text:
        return "apply_fail"

    if normalized_language == "python":
        if "SyntaxError" in text or "IndentationError" in text:
            return "compilation_fail"
        return "validation_fail"

    if normalized_language == "javascript":
        if "SyntaxError" in text or "TypeError" in text:
            return "compilation_fail"
        return "validation_fail"

    if normalized_language == "go":
        if re.search(r"^.*\.go:\d+:\d+: ", text, re.MULTILINE) and not re.search(r"panic:", text):
            return "compilation_fail"
        return "validation_fail"

    return "validation_fail"


def _workspace_root(validate_dir: str) -> str:
    return os.path.dirname(os.path.normpath(validate_dir)) or "/"


def _append_classified_failure(logs: list[str], step_name: str, rc: int, stdout: str, stderr: str, language: str) -> str:
    error_text = f"{stdout or ''}\n{stderr or ''}"
    logs.append(_format_step(step_name, rc, stdout, stderr))
    logs.append(f"error_type={_classify_patcheval_error(error_text, language)}\n")
    return "".join(logs)


def _validate_local_patcheval_patch(
    immutable_dir: str,
    validate_dir: str,
    patch_text: str,
    language: str,
) -> tuple[bool, str]:
    logs: list[str] = []
    ok, prep_logs = _prepare_local_patcheval_validate_dir(immutable_dir, validate_dir)
    logs.extend(prep_logs)
    if not ok:
        return False, "".join(logs)

    workspace_root = _workspace_root(validate_dir)
    patch_path = os.path.join(workspace_root, "fix.patch")
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch_text)

    rc, out, err = _run_local_command("bash prepare.sh", cwd=workspace_root)
    if rc != 0:
        return False, _append_classified_failure(logs, "prepare.sh", rc, out, err, language)

    rc, out, err = _run_local_command("bash fix-run.sh", cwd=workspace_root)
    if rc != 0:
        return False, _append_classified_failure(logs, "fix-run.sh", rc, out, err, language)

    rc, out, err = _run_local_command("bash prepare.sh", cwd=workspace_root)
    if rc != 0:
        return False, _append_classified_failure(logs, "prepare.sh", rc, out, err, language)

    rc, _, _ = _run_local_command("test -f unit_test.sh", cwd=workspace_root)
    if rc == 0:
        rc, out, err = _run_local_command("bash unit_test.sh", cwd=workspace_root)
        if rc != 0:
            return False, _append_classified_failure(logs, "unit_test.sh", rc, out, err, language)

    return True, "".join(logs)


def _validate_docker_patcheval_patch(
    exec_container: str,
    immutable_dir: str,
    validate_dir: str,
    patch_text: str,
    language: str,
    patch_container_path: str,
) -> tuple[bool, str]:
    logs: list[str] = []
    ok, prep_logs = _prepare_docker_patcheval_validate_dir(exec_container, immutable_dir, validate_dir)
    logs.extend(prep_logs)
    if not ok:
        return False, "".join(logs)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".patch") as patch_file:
        patch_file.write(patch_text)
        local_patch_path = patch_file.name

    try:
        rc, out, err = _docker_cp_to_container(local_patch_path, exec_container, patch_container_path)
        _append_failed_step(logs, "docker cp", rc, out, err)
        if rc != 0:
            return False, "".join(logs)
    finally:
        Path(local_patch_path).unlink(missing_ok=True)

    workspace_root = _workspace_root(validate_dir)
    rc, out, err = _docker_exec(exec_container, workspace_root, "bash prepare.sh")
    if rc != 0:
        return False, _append_classified_failure(logs, "prepare.sh", rc, out, err, language)

    rc, out, err = _docker_exec(exec_container, workspace_root, "bash fix-run.sh")
    if rc != 0:
        return False, _append_classified_failure(logs, "fix-run.sh", rc, out, err, language)

    rc, out, err = _docker_exec(exec_container, workspace_root, "bash prepare.sh")
    if rc != 0:
        return False, _append_classified_failure(logs, "prepare.sh", rc, out, err, language)

    rc, _, _ = _docker_exec(exec_container, workspace_root, "test -f unit_test.sh")
    if rc == 0:
        rc, out, err = _docker_exec(exec_container, workspace_root, "bash unit_test.sh")
        if rc != 0:
            return False, _append_classified_failure(logs, "unit_test.sh", rc, out, err, language)

    return True, "".join(logs)


def validate_patcheval_patch_v2(
    instance_id: str,
    patch_text: str,
    container_name: str,
    immutable_dir: Optional[str] = None,
    validate_dir: Optional[str] = None,
    language: str = "",
    patch_container_path: Optional[str] = None,
) -> tuple[bool, str]:
    immutable_dir = immutable_dir or ""
    validate_dir = validate_dir or ""
    workspace_root = _workspace_root(validate_dir)
    patch_container_path = patch_container_path or os.path.join(workspace_root, "fix.patch")
    print(f"Validating patch with instance_id={instance_id}, container_name={container_name}, immutable_dir={immutable_dir}, validate_dir={validate_dir}, language={language}, patch_container_path={patch_container_path}")

    if running_inside_dataset_container():
        return _validate_local_patcheval_patch(
            immutable_dir=immutable_dir,
            validate_dir=validate_dir,
            patch_text=patch_text,
            language=language,
        )

    logs: list[str] = []
    exec_container, setup_log = _ensure_exec_container(instance_id, container_name)
    if setup_log:
        logs.append(setup_log)
    if exec_container is None:
        return False, "".join(logs)

    ok, report = _validate_docker_patcheval_patch(
        exec_container=exec_container,
        immutable_dir=immutable_dir,
        validate_dir=validate_dir,
        patch_text=patch_text,
        language=language,
        patch_container_path=patch_container_path,
    )
    if not ok and logs:
        return False, "".join(logs) + report
    return ok, "".join(logs) + report
