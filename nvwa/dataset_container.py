import os
import re
import shlex
import subprocess

from dataclasses import dataclass


CONTAINERIZED_DATASETS = {"patcheval", "secbench", "vul4j", "vjbench"}
RUNNING_IN_DATASET_CONTAINER_ENV = "NVWA_RUNNING_IN_DATASET_CONTAINER"
DATASET_NAME_ENV = "NVWA_DATASET_NAME"
DATASET_CASE_ENV = "NVWA_DATASET_CASE"
DATASET_IMAGE_ENV = "NVWA_DATASET_IMAGE"


@dataclass(frozen=True)
class DatasetContainerTask:
    dataset: str
    tag: str
    container_name: str


def should_containerize_dataset(dataset: str) -> bool:
    return dataset in CONTAINERIZED_DATASETS


def running_inside_dataset_container() -> bool:
    return os.getenv(RUNNING_IN_DATASET_CONTAINER_ENV, "").strip() == "1"


def _sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.").lower()
    return sanitized or "case"


def _container_name(task: DatasetContainerTask) -> str:
    return f"nvwa-{_sanitize_name(task.dataset)}-{_sanitize_name(task.tag)}-{os.getpid()}"


def _mount_dirs_from_args(cwd: str, inner_args: list[str]) -> list[str]:
    mount_dirs: list[str] = []
    for index, arg in enumerate(inner_args):
        if arg not in {"--dataset_path", "--log_path"}:
            continue
        if index + 1 >= len(inner_args):
            continue
        raw_path = inner_args[index + 1]
        if not raw_path:
            continue
        normalized = os.path.abspath(os.path.expanduser(raw_path))
        mount_dir = normalized if os.path.isdir(normalized) else os.path.dirname(normalized)
        if not mount_dir or mount_dir == cwd:
            continue
        if mount_dir.startswith(cwd.rstrip(os.sep) + os.sep):
            continue
        if mount_dir not in mount_dirs:
            mount_dirs.append(mount_dir)
    return mount_dirs


def build_container_command(task: DatasetContainerTask, cwd: str, inner_args: list[str]) -> list[str]:
    cwd = os.path.abspath(cwd)
    script_path = os.path.join(cwd, "nwtool")
    container_name = _container_name(task)

    args = [
        "docker",
        "run",
        "--rm",
        "--name", container_name,
        "-w", cwd,
        "-v", f"{cwd}:{cwd}",
        "-v", "agent_venv:/opt/venv:ro",
        "-v", "agent_tools:/opt/tools:ro",
        "-v", "/opt/jdtls:/opt/jdtls",
        "-v", "/usr/lib/jvm/jdk-21.0.7+6:/usr/lib/jvm/jdk-21.0.7+6",
        "--entrypoint",
        "/bin/bash",
    ]

    for mount_dir in _mount_dirs_from_args(cwd, inner_args):
        args.extend(["-v", f"{mount_dir}:{mount_dir}"])
    
    if task.dataset == "vul4j":
        args.extend([
            "-v", "/cache_vul4j/m2:/root/.m2",
            "-v", "/cache_vul4j/gradle:/root/.gradle",
        ])
    elif task.dataset == "vjbench":
        args.extend([
            "-v", "/cache/m2:/root/.m2",
            "-v", "/cache/gradle:/root/.gradle",
        ])

    inner_env = [
        f"export {RUNNING_IN_DATASET_CONTAINER_ENV}=1",
        f"export {DATASET_NAME_ENV}={shlex.quote(task.dataset)}",
        f"export {DATASET_CASE_ENV}={shlex.quote(task.tag)}",
        f"export {DATASET_IMAGE_ENV}={shlex.quote(task.container_name)}",
        "export VIRTUAL_ENV=/opt/venv",
        "export PATH=/opt/venv/bin:/opt/tools:$PATH",
    ]
    if task.dataset == "vjbench":
        inner_env.append("export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 && export PATH=$JAVA_HOME/bin:$PATH &&")
    if task.dataset in {"patcheval", "vul4j", "vjbench"}:
        inner_env.append("apt-get update && apt-get install -y universal-ctags")
    elif task.dataset == "secbench":
        inner_env.append("apt-get update && apt-get install -y universal-ctags bear")
        # inner_env.append(
        #     f"wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key --no-check-certificate| apt-key add - && "
        #     f" add-apt-repository \"deb http://apt.llvm.org/focal/ llvm-toolchain-focal-16 main\" && "
        #     f"apt-get update && apt-get install -y libclang-16-dev clang-16 clangd-16"
        # )
    inner_env.append(
        f"cd {shlex.quote(cwd)} && "
        f"source .venv/bin/activate && "
        f"{shlex.quote(script_path)} {shlex.join(inner_args)}"
    )

    args.extend([task.container_name, "-lc", " && ".join(inner_env)])
    return args


def run_case_in_container(task: DatasetContainerTask, cwd: str, inner_args: list[str]) -> int:
    command = build_container_command(task, cwd, inner_args)
    completed = subprocess.run(command, stdout=None, stderr=None)
    return completed.returncode
