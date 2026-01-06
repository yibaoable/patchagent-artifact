"""
    SkySet dataset structure:
    
    {project}/
        build.sh
        {commit-info}/
            immutable/
            mutable/
            exp.sh
            report.txt
            @POC@
            config.yml
"""

import os
import git
import yaml
import shutil
import tempfile
import subprocess

from typing import Union, Optional


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
ASANCC = os.path.join(ROOT, "skyset_tools", "compiler", "asancc")
ASANCXX = os.path.join(ROOT, "skyset_tools", "compiler", "asan++")
UBSANCC = os.path.join(ROOT, "skyset_tools", "compiler", "ubsancc")
UBSANCXX = os.path.join(ROOT, "skyset_tools", "compiler", "ubsan++")
BEARCC = os.path.join(ROOT, "skyset_tools", "compiler", "bearcc")
BEARCXX = os.path.join(ROOT, "skyset_tools", "compiler", "bear++")

SYZ_SYMBOLIZER = os.path.join(ROOT, "skyset_tools", "skykaller", "bin", "syz-symbolize")
# print("SYZ_SYMBOLIZER:",SYZ_SYMBOLIZER)
# assert os.path.exists(SYZ_SYMBOLIZER)


def get_commit(tag: str) -> str:
    return tag if "-" not in tag else tag.split("-")[0]


def get_sky_path(project: str, tag: str) -> str:
    return os.path.join(ROOT, project, tag)


def get_build_script_path(project: str) -> str:
    return os.path.join(ROOT, project, "build.sh")


def get_pull_script_path(project: str) -> str:
    return os.path.join(ROOT, project, "pull.sh")


def get_test_functional_script_path(project: str) -> str:
    return os.path.join(ROOT, project, "test.sh")


def get_report_path(project: str, tag: str) -> str:
    return os.path.join(get_sky_path(project, tag), "report.txt")


def get_exp_script_path(project: str, tag: str) -> str:
    return os.path.join(get_sky_path(project, tag), "exp.sh")


def get_poc_path(project: str, tag: str) -> str:
    return os.path.join(get_sky_path(project, tag), "@POC@")


def get_immutable_path(project: str, tag: str) -> str:
    return os.path.join(get_sky_path(project, tag), "immutable")


def get_sanitizer_build_path(project: str, tag: str, sanitizer: str, patch: bool = False) -> str:
    return os.path.join(get_sky_path(project, tag), f"{sanitizer}{'_Patch' if patch else ''}")


def get_functional_test_path(project: str, tag: str, patch: bool = False) -> str:
    return os.path.join(get_sky_path(project, tag), f"Functional{'_Patch' if patch else ''}")


def get_config(project: str, tag: str) -> dict:
    config_path = os.path.join(get_sky_path(project, tag), "config.yml")
    if not os.path.exists(config_path):
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f)


def cleanup(repo_path: str):
    repo = git.Repo(repo_path)
    repo.git.clean("-xdf")
    repo.git.reset("--hard")

    for root, dirs, _ in os.walk(repo_path):
        if ".git" in dirs and root != repo_path:
            shutil.rmtree(os.path.join(root), ignore_errors=True)


def apply_patch(repo_path: str, patch_path: str) -> bool:
    p = subprocess.run(
        ["patch", "-p1", "-i", patch_path, "--batch"],
        cwd=repo_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return p.returncode == 0

def apply_git_diff(workdir: str, diff_text: str) -> bool:
    """将 diff 文本应用到工作副本。"""
    def run_command(cmd: str, cwd: Optional[str] = None, timeout: int = 300):
        """执行shell命令，返回 (success, stdout, stderr)。"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout
            )
            if result.returncode == 0:
                return True, result.stdout, result.stderr
            else:
                return False, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            return False, "", "Command timeout"
        except Exception as e:
            return False, "", str(e) 
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.patch') as tf:
        tf.write(diff_text)
        tf.flush()
        tmp_path = tf.name
    try:
        success, _, stderr = run_command(f"git apply {tmp_path}", cwd=workdir)
        if not success:
            success, _, stderr = run_command(f"git apply --ignore-whitespace {tmp_path}", cwd=workdir)
            if not success:
                success, _, stderr = run_command(f"git apply --ignore-space-change --ignore-whitespace {tmp_path}", cwd=workdir)
                if not success:
                    return False
        return True
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass 

def regenerate_patch(project: str, tag: str, patch_path: str) -> tuple[bool, str]:
    immutable_path = get_immutable_path(project, tag)
    repo = git.Repo(immutable_path)

    ret, patch = apply_patch(immutable_path, patch_path), ""
    if ret:
        f = tempfile.NamedTemporaryFile(delete=False)
        subprocess.run(
            ["git", "diff", "--output", f.name],
            cwd=immutable_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(f.name) as f:
            filtered_lines = [l for l in f.readlines() if not l.startswith(("diff --git", "index "))]
            patch = "".join(filtered_lines)

        os.unlink(f.name)

    repo.git.reset("--hard")
    repo.git.clean("-xdf")
    return (ret, patch)


def pull_immutable(project: str, tag: str):
    immutable_path = get_immutable_path(project, tag)
    env = os.environ.copy()
    env.update({"SRC": immutable_path})
    subprocess.check_call(
        [get_pull_script_path(project)],
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    immutable_repo = git.Repo(immutable_path)
    immutable_repo.git.checkout(get_commit(tag))


def checkout(
    project: str,
    tag: str,
    sanitizer: str,
    patch_path: Union[str, None] = None,
    rebuild: bool = True,
) -> tuple[bool, str]:
    mutable_path = get_sanitizer_build_path(project, tag, sanitizer, patch_path is not None)
    immutable_path = get_immutable_path(project, tag)

    if not os.path.exists(immutable_path):
        pull_immutable(project, tag)

    if not os.path.exists(mutable_path):
        shutil.copytree(immutable_path, mutable_path)

    if rebuild:
        if sanitizer == "KernelAddressSanitizer":
            repo = git.Repo(mutable_path)
            repo.git.reset("--hard")
        else:
            cleanup(mutable_path)

    assert git.Repo(mutable_path).head.object.hexsha.startswith(get_commit(tag))

    return True, ""

    # if patch_payload:
    #     if not apply_git_diff(mutable_path, patch_payload):
    #         return (False, "Patch failed to apply")

    # elif patch_path is not None:
    #     if not apply_patch(mutable_path, patch_path):
    #         return (False, "Patch failed to apply")

def compile(
    project: str,
    tag: str,
    sanitizer: str,
    patch_path: Union[str, None] = None,
    rebuild: bool = True,
) -> tuple[bool, str]:
    mutable_path = get_sanitizer_build_path(project, tag, sanitizer, patch_path is not None)
    if sanitizer == "AddressSanitizer":
        env = os.environ.copy()
        env.update(
            {
                "CC": ASANCC,
                "CXX": ASANCXX,
                ## HACK: Disable halt_on_error to avoid stopping the build process
                "ASAN_OPTIONS": "halt_on_error=0",
            }
        )
        build_process = subprocess.Popen(
            [get_build_script_path(project)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=mutable_path,
            env=env,
            shell=True,
            executable="/bin/bash",
        )
        try:
            stdout, stderr = build_process.communicate(timeout=60 * 60)
            print(stderr)
        except subprocess.TimeoutExpired:
            build_process.kill()
            return (False, "Compilation Timeout")

        if build_process.returncode != 0:
            return (False, "Compilation failed")

    elif sanitizer == "UndefinedBehaviorSanitizer":
        env = os.environ.copy()
        env.update(
            {
                "CC": UBSANCC,
                "CXX": UBSANCXX,
                "UBSAN_OPTIONS": "halt_on_error=0",
            }
        )
        build_process = subprocess.Popen(
            [get_build_script_path(project)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=mutable_path,
            env=env,
            shell=True,
            executable="/bin/bash",
        )
        stdout, stderr = build_process.communicate()

        if build_process.returncode != 0:
            return (False, "Compilation failed")

    elif sanitizer == "BearSanitizer":
        origin_sanitizer = get_config(project, tag)["sanitizer"]
        if origin_sanitizer in ["AddressSanitizer", "UndefinedBehaviorSanitizer"]:
            compile_commands_log = os.path.join(mutable_path, "compile_commands.log")
            env = os.environ.copy()
            env.update(
                {
                    "CC": BEARCC,
                    "CXX": BEARCXX,
                    "BEAR_LOG_PATH": compile_commands_log,
                }
            )
            if os.path.exists(compile_commands_log):
                os.unlink(compile_commands_log)
            build_process = subprocess.Popen(
                [get_build_script_path(project)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=mutable_path,
                env=env,
                shell=True,
                executable="/bin/bash",
            )
        elif origin_sanitizer in ["KernelAddressSanitizer"]:
            compile_commands_json = os.path.join(mutable_path, "compile_commands.json")
            if os.path.exists(compile_commands_json):
                os.unlink(compile_commands_json)

            build_process = subprocess.Popen(
                f"bear -- {get_build_script_path(project)}",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=mutable_path,
                env=os.environ,
                shell=True,
                executable="/bin/bash",
            )

        stdout, stderr = build_process.communicate()
        if build_process.returncode != 0:
            return (False, "Compilation failed")

    elif sanitizer == "KernelAddressSanitizer":
        env = os.environ.copy()
        build_process = subprocess.Popen(
            [get_build_script_path(project)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=mutable_path,
            env=env,
            shell=True,
            executable="/bin/bash",
        )
        stdout, stderr = build_process.communicate()
        if build_process.returncode != 0:
            return (False, "Compilation failed")
    elif sanitizer == "KernelUndefinedBehaviorSanitizer":
        env = os.environ.copy()
        build_process = subprocess.Popen(
            [get_build_script_path(project)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=mutable_path,
            env=env,
            shell=True,
            executable="/bin/bash",
        )
        stdout, stderr = build_process.communicate()
        if build_process.returncode != 0:
            return (False, "Compilation failed")
    else:
        return (False, f"Sanitizer {sanitizer} not supported")

    return (True, "")


def test(
    project: str,
    tag: str,
    sanitizer: str,
    patch: bool = False,
    poc_path: Union[str, None] = None,
) -> tuple[bool, str]:
    """
        The test function is responsible for running the experiment script
        and returning the output of the sanitizer log file.
        
        If no unexpected behavior is found, the function returns (True, report), the report may be empty.
        Otherwise, the function returns (False, report), the report contains the unexpected behavior.
    """
    mutable_path = get_sanitizer_build_path(project, tag, sanitizer, patch)
    if poc_path is not None:
        if not os.path.exists(poc_path):
            return (False, f"POC path {poc_path} does not exist")

        shutil.copyfile(poc_path, os.path.join(mutable_path, "@POC@"))
    else:
        shutil.copyfile(get_poc_path(project, tag), os.path.join(mutable_path, "@POC@"))

    exp_script_path = get_exp_script_path(project, tag)
    if sanitizer == "AddressSanitizer":
        env = os.environ.copy()
        env.update(
            {
                "ASAN_OPTIONS": "detect_leaks=0,verify_asan_link_order=0,log_path=./asan_log.txt",
            }
        )
        test_process = subprocess.Popen(
            [exp_script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=mutable_path,
            shell=True,
            executable="/bin/bash",
        )
        for file in os.listdir(mutable_path):
            if file.startswith("asan_log.txt."):
                os.unlink(os.path.join(mutable_path, file))

        try:
            stdout, stderr = test_process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            test_process.kill()
            return (False, "Timeout")

        for file in os.listdir(mutable_path):
            if file.startswith("asan_log.txt."):
                with open(os.path.join(mutable_path, file)) as f:
                    return (True, f.read().replace(mutable_path, f"/root"))
        else:
            return (True, "")

    elif sanitizer == "UndefinedBehaviorSanitizer":
        env = os.environ.copy()
        env.update(
            {
                "UBSAN_OPTIONS": "halt_on_error=1,log_path=./ubsan_log.txt,print_stacktrace=1",
            }
        )
        test_process = subprocess.Popen(
            [exp_script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=mutable_path,
            shell=True,
            executable="/bin/bash",
        )
        for file in os.listdir(mutable_path):
            if file.startswith("ubsan_log.txt."):
                os.unlink(os.path.join(mutable_path, file))

        try:
            stdout, stderr = test_process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            test_process.kill()
            return (False, "Timeout")

        for file in os.listdir(mutable_path):
            if file.startswith("ubsan_log.txt."):
                with open(os.path.join(mutable_path, file)) as f:
                    return (True, f.read().replace(mutable_path, f"/root"))
        else:
            return (True, "")

    elif sanitizer == "KernelAddressSanitizer":
        env = os.environ.copy()
        test_process = subprocess.Popen(
            [exp_script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=mutable_path,
            shell=True,
            executable="/bin/bash",
        )
        for file in os.listdir(mutable_path):
            if file == "qemu.log":
                os.unlink(os.path.join(mutable_path, file))

        try:
            stdout, stderr = test_process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            test_process.kill()
            return (False, "Timeout")

        for file in os.listdir(mutable_path):
            if file == "qemu.log":
                proc = subprocess.Popen(
                    [SYZ_SYMBOLIZER, os.path.join(mutable_path, file)],
                    cwd=mutable_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                rep, _ = proc.communicate()
                rep = rep.replace(b"\r\r", b"").decode()
                if "BUG: KASAN:" in rep:
                    return (True, rep[rep.index("BUG: KASAN:") :])
                
                # HACK: kernel panic but no KASAN report generated
                if "Kernel panic" in rep:
                    return (False, "Kernel panic")
        else:
            return (True, "")
    else:
        return (False, f"Sanitizer {sanitizer} not supported")


def test_functional(
    project: str,
    tag: str,
    sanitizer: str,
    patch_path: Union[str, None] = None,
) -> dict:
    mutable_path = get_sanitizer_build_path(project, tag, sanitizer, patch_path is not None)
    immutable_path = get_immutable_path(project, tag)

    if not os.path.exists(immutable_path):
        pull_immutable(project, tag)

    if not os.path.exists(mutable_path):
        shutil.copytree(get_immutable_path(project, tag), mutable_path)

    # cleanup(mutable_path)
    test_functional_script_path = get_test_functional_script_path(project)
    # if patch_path:
    #     apply_patch(mutable_path, patch_path)

    if not os.path.exists(test_functional_script_path):
        return {
            "result": "unknown",
            "returncode": -1,
            "stdout": "",
            "stderr": "",
        }
    test_process = subprocess.Popen(
        [test_functional_script_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=mutable_path,
        shell=True,
        executable="/bin/bash",
    )
    try:
        stdout, stderr = test_process.communicate(timeout=60 * 60 * 2)
    except subprocess.TimeoutExpired:
        test_process.kill()
        return {
            "result": "failed",
            "returncode": -1,
            "stdout": "",
            "stderr": "",
        }

    result = {
        "result": "passed" if test_process.returncode == 0 else "failed",
        "returncode": test_process.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

    return result
