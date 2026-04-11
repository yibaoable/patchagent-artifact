import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading

from pathlib import Path

from nvwa.dataset_container import running_inside_dataset_container


def _vul4j_compile_success(output: str) -> bool:
    return "Compile failed!" not in output

def _vul4j_test_success(output: str) -> bool:
    print(f"Vul4J Test Output:\n{output}\n{'-'*60}")
    text = output
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if re.search(r'Number of running tests:\s*0', text, re.IGNORECASE):
        return False
    try:
        data = json.loads(json_match.group())
        tests = data.get('tests', {})
        overall_metrics = tests.get('overall_metrics', {})
        number_error = overall_metrics.get('number_error', 0)
        number_failing = overall_metrics.get('number_failing', 0)
        failures = tests.get('failures', [])
        if number_error > 0 or number_failing > 0 or len(failures) > 0:
            return False
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        return False
    except Exception as e:
        print(f"解析错误: {e}")
        return False
    return True


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines = []
    stderr_lines = []
    
    def read_output(pipe, lines):
        for line in iter(pipe.readline, ''):
            print(line, end='', flush=True)
            lines.append(line)
    
    threads = []
    if process.stdout:
        t = threading.Thread(target=read_output, args=(process.stdout, stdout_lines))
        t.start()
        threads.append(t)
    if process.stderr:
        t = threading.Thread(target=read_output, args=(process.stderr, stderr_lines))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    process.wait()
    return process.returncode, ''.join(stdout_lines), ''.join(stderr_lines)


def _run_local_command(cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
    process = subprocess.Popen(
        ["bash", "-lc", cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines = []
    stderr_lines = []
    
    def read_output(pipe, lines):
        for line in iter(pipe.readline, ''):
            print(line, end='', flush=True)
            lines.append(line)
    
    threads = []
    if process.stdout:
        t = threading.Thread(target=read_output, args=(process.stdout, stdout_lines))
        t.start()
        threads.append(t)
    if process.stderr:
        t = threading.Thread(target=read_output, args=(process.stderr, stderr_lines))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    process.wait()
    return process.returncode, ''.join(stdout_lines), ''.join(stderr_lines)


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


def _runtime_container_name(vuln_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", vuln_id).strip("-.").lower()
    prefix = os.getenv("VUL4J_RUNTIME_CONTAINER_PREFIX", "vul4j")
    return f"{prefix}-{sanitized}" if prefix else sanitized


def _docker_container_exists(container: str) -> bool:
    rc, _, _ = _run_command(["docker", "inspect", "--type=container", container])
    return rc == 0


def _docker_container_running(container: str) -> bool:
    rc, out, _ = _run_command(["docker", "inspect", "-f", "{{.State.Running}}", container])
    return rc == 0 and out.strip().lower() == "true"


def _docker_start(container: str) -> bool:
    rc, _, _ = _run_command(["docker", "start", container])
    return rc == 0


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
            "apt-get update && apt-get install -y llvm llvm-14 llvm-14-tools",
        ]
    )
    return _format_step("install llvm", rc, out, err)


def _ensure_exec_container(vuln_id: str, image: str, work_dir: str) -> tuple[str | None, str]:
    runtime_container = _runtime_container_name(vuln_id)
    exists = _docker_container_exists(runtime_container)
    if exists:
        if not _docker_container_running(runtime_container) and not _docker_start(runtime_container):
            return None, ""
        install_log = _install_llvm(runtime_container)
        return runtime_container, install_log

    extra_mounts: list[str] = []
    if work_dir:
        extra_mounts.extend(["-v", f"{work_dir}:{work_dir}"])

    created, step_log = _docker_run_background(image, runtime_container, extra_mounts=extra_mounts)
    if not created:
        return None, step_log

    install_log = _install_llvm(runtime_container)
    return runtime_container, step_log + install_log


def _skip_compile_cases() -> set[str]:
    return {item.strip() for item in os.getenv("SKIP_COMPILE", "").split(",") if item.strip()}


def _container_path_exists(container: str, path: str) -> bool:
    rc, _, _ = _docker_exec_root(container, f"test -d {shlex.quote(path)}")
    return rc == 0


def _path_exists(path: str) -> bool:
    return os.path.exists(path)


def _local_validate_dir_has_checkout_contents(path: str) -> bool:
    if not os.path.isdir(path):
        return False

    try:
        with os.scandir(path) as entries:
            return any(entry.name != ".git" for entry in entries)
    except OSError:
        return False


def _container_validate_dir_has_checkout_contents(container: str, path: str) -> bool:
    rc, out, _ = _docker_exec_root(
        container,
        f"find {shlex.quote(path)} -mindepth 1 -maxdepth 1 ! -name .git -print -quit",
    )
    return rc == 0 and bool(out.strip())


def _remove_local_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
        return
    os.unlink(path)


def prepare_vul4j_immutable_dir(vuln_id: str, immutable_dir: str, remove_vul4j_dir: bool = True) -> tuple[bool, str]:
    logs: list[str] = []
    parent = os.path.dirname(immutable_dir) or "/"
    rc, out, err = _run_local_command(
        f"rm -rf {shlex.quote(immutable_dir)} && mkdir -p {shlex.quote(parent)} && vul4j checkout -i {shlex.quote(vuln_id)} -d {shlex.quote(immutable_dir)}"
    )
    _append_failed_step(logs, "prepare immutable dir", rc, out, err)
    if rc != 0:
        return False, "".join(logs)

    if remove_vul4j_dir:
        try:
            shutil.rmtree(os.path.join(immutable_dir, "VUL4J"), ignore_errors=True)
        except OSError as exc:
            logs.append(_format_step("remove VUL4J from immutable", 1, "", str(exc)))
            return False, "".join(logs)

    return True, "".join(logs)


def _prepare_local_validate_dir(vuln_id: str, validate_dir: str) -> tuple[bool, list[str]]:
    logs: list[str] = []
    validate_exists = _path_exists(validate_dir)
    validate_ready = validate_exists and _path_exists(os.path.join(validate_dir, ".git")) and _local_validate_dir_has_checkout_contents(validate_dir)

    if validate_ready:
        rc, out, err = _run_local_command(
            f"git -C {shlex.quote(validate_dir)} reset --hard && git -C {shlex.quote(validate_dir)} clean -xdf"
        )
        _append_failed_step(logs, "clean validate dir", rc, out, err)
        if rc != 0:
            return False, logs
        return True, logs

    if validate_exists:
        try:
            _remove_local_path(validate_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logs.append(_format_step("remove broken validate dir", 1, "", str(exc)))
            return False, logs

    parent = os.path.dirname(validate_dir) or "/"
    rc, out, err = _run_local_command(
        f"mkdir -p {shlex.quote(parent)} && vul4j checkout -i {shlex.quote(vuln_id)} -d {shlex.quote(validate_dir)}"
    )
    _append_failed_step(logs, "checkout validate dir", rc, out, err)
    if rc != 0:
        return False, logs
    return True, logs


def _validate_local_vul4j_patch(
    vuln_id: str,
    patch_text: str,
    validate_dir: str,
) -> tuple[bool, str]:
    logs: list[str] = []
    ok, prep_logs = _prepare_local_validate_dir(vuln_id, validate_dir)
    logs.extend(prep_logs)
    if not ok:
        return False, "".join(logs)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".diff") as patch_file:
        patch_file.write(patch_text)
        patch_path = patch_file.name

    try:

        rc, out, err = _run_local_command(f"git apply {shlex.quote(patch_path)}", cwd=validate_dir)
        _append_failed_step(logs, "git apply", rc, out, err)
        if rc != 0:
            return False, "".join(logs)

        if vuln_id not in _skip_compile_cases():
            rc, out, err = _run_local_command(f"vul4j compile -d {shlex.quote(validate_dir)}")
            logs.append(_format_step("vul4j compile", rc, out, err))
            if rc != 0 or not _vul4j_compile_success(out + err):
                return False, "".join(logs)

        rc, out, err = _run_local_command(f"vul4j test -d {shlex.quote(validate_dir)}")
        logs.append(_format_step("vul4j test", rc, out, err))
        if rc != 0 or not _vul4j_test_success(out + err):
            return False, "".join(logs)
    finally:
        Path(patch_path).unlink(missing_ok=True)

    return True, "".join(logs)


def validate_vul4j_patch_v2(
    vuln_id: str,
    patch_text: str,
    container_name: str,
    work_dir: str,
    validate_dir: str | None = None,
    patch_container_path: str = "/tmp/model_patch.diff",
) -> tuple[bool, str]:
    validate_dir = validate_dir or f"{work_dir}_Patch"

    if running_inside_dataset_container():
        return _validate_local_vul4j_patch(vuln_id, patch_text, validate_dir)

    logs: list[str] = []
    exec_container, setup_log = _ensure_exec_container(vuln_id, container_name, work_dir)
    if exec_container is None:
        if setup_log:
            logs.append(setup_log)
        return False, "".join(logs)

    immutable_dir = work_dir
    if not _container_path_exists(exec_container, immutable_dir):
        rc, out, err = _docker_exec_root(
            exec_container,
            f"rm -rf {shlex.quote(immutable_dir)} && mkdir -p {shlex.quote(os.path.dirname(immutable_dir) or '/')} && vul4j checkout -i {shlex.quote(vuln_id)} -d {shlex.quote(immutable_dir)}",
        )
        _append_failed_step(logs, "prepare immutable dir", rc, out, err)
        if rc != 0:
            return False, "".join(logs)
        rc, out, err = _docker_exec_root(exec_container, f"rm -rf {shlex.quote(os.path.join(immutable_dir, 'VUL4J'))}")
        _append_failed_step(logs, "remove VUL4J from immutable", rc, out, err)
        if rc != 0:
            return False, "".join(logs)

    validate_exists = _container_path_exists(exec_container, validate_dir)
    validate_ready = validate_exists and _container_validate_dir_has_checkout_contents(exec_container, validate_dir)
    if validate_ready:
        rc, out, err = _docker_exec_root(
            exec_container,
            f"git -C {shlex.quote(validate_dir)} reset --hard && git -C {shlex.quote(validate_dir)} clean -xdf",
        )
        _append_failed_step(logs, "clean validate dir", rc, out, err)
        if rc != 0:
            return False, "".join(logs)
    else:
        if validate_exists:
            rc, out, err = _docker_exec_root(exec_container, f"rm -rf {shlex.quote(validate_dir)}")
            _append_failed_step(logs, "remove broken validate dir", rc, out, err)
            if rc != 0:
                return False, "".join(logs)

        rc, out, err = _docker_exec_root(
            exec_container,
            f"mkdir -p {shlex.quote(os.path.dirname(validate_dir) or '/')} && vul4j checkout -i {shlex.quote(vuln_id)} -d {shlex.quote(validate_dir)}",
        )
        _append_failed_step(logs, "checkout validate dir", rc, out, err)
        if rc != 0:
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

    if vuln_id not in _skip_compile_cases():
        compile_cmd = f"export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 && export PATH=$JAVA_HOME/bin:$PATH && vul4j compile -d {shlex.quote(validate_dir)}"
        rc, out, err = _docker_exec_root(exec_container, compile_cmd)
        logs.append(_format_step("initial vul4j compile", rc, out, err))
        if rc != 0 or not _vul4j_compile_success(out + err):
            return False, "".join(logs)

    rc, out, err = _docker_exec(exec_container, validate_dir, f"git apply {shlex.quote(patch_container_path)}")
    _append_failed_step(logs, "git apply", rc, out, err)
    if rc != 0:
        return False, "".join(logs)

    if vuln_id not in _skip_compile_cases():
        compile_cmd = f"export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 && export PATH=$JAVA_HOME/bin:$PATH && vul4j compile -d {shlex.quote(validate_dir)}"
        rc, out, err = _docker_exec_root(exec_container, compile_cmd)
        if rc != 0 or not _vul4j_compile_success(out + err):
            logs.append(_format_step("vul4j compile", rc, out, err))
            return False, "".join(logs)

    test_cmd = f"export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 && export PATH=$JAVA_HOME/bin:$PATH && vul4j test -d {shlex.quote(validate_dir)}"
    rc, out, err = _docker_exec_root(exec_container, test_cmd)
    if rc != 0 or not _vul4j_test_success(out + err):
        logs.append(_format_step("vul4j test", rc, out, err))
        return False, "".join(logs)

    return True, "".join(logs)
