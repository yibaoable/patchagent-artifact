import json
import os

from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
VJBENCH_MARKERS = ("buggy_file_path", "cve_description", "github_url")


def _default_container_name() -> str:
    return os.getenv("VJBENCH_IMAGE", "java_env:latest")


def _default_work_dir(vuln_id: str) -> str:
    work_root = os.getenv("VJBENCH_WORK_ROOT", "/tmp/vjbench")
    return os.path.join(work_root, vuln_id)


def _normalize_project_name(key: Optional[str], config: dict) -> str:
    if config.get("project_name"):
        return str(config["project_name"])
    if config.get("project"):
        return str(config["project"])
    github_url = str(config.get("github_url") or "").rstrip("/")
    if github_url:
        return github_url.rsplit("/", 1)[-1].lower()
    if key and "-" in key:
        return key.rsplit("-", 1)[0].lower()
    return str(key or "")


def _looks_like_vjbench_config(key: Optional[str], config: dict) -> bool:
    if any(marker in config for marker in VJBENCH_MARKERS):
        return True
    if key is None:
        return False
    return "-" in key


def _normalize_case(key: Optional[str], raw_case: dict) -> dict:
    if not isinstance(raw_case, dict):
        raise ValueError("VJBench dataset entries must be JSON objects")
    if key is None:
        raise ValueError("VJBench dataset entries must be keyed by vuln id")

    case = dict(raw_case)
    if not _looks_like_vjbench_config(key, case):
        raise ValueError("Not a VJBench dataset entry")

    case["instance_id"] = str(key)
    case["vuln_id"] = str(key)
    case["project_name"] = _normalize_project_name(key, case)
    case.setdefault("container_name", _default_container_name())
    case.setdefault("work_dir", _default_work_dir(case["vuln_id"]))
    case.setdefault("dataset", "vjbench")
    case["input_mode"] = "vuln_func"
    return case


def _candidate_dataset_paths() -> Iterable[Path]:
    env_path = os.getenv("VJBENCH_DATASET_JSON")
    if env_path:
        yield Path(env_path).expanduser()

    for name in (
        "vjbench_dataset.json",
    ):
        yield REPO_ROOT / "skyset" / name


def find_vjbench_dataset_path(dataset_path: Optional[str] = None) -> str:
    candidates = [Path(dataset_path).expanduser()] if dataset_path else []
    candidates.extend(_candidate_dataset_paths())

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loader = VJBenchDatasetLoader(str(candidate))
            loader.load()
            return str(candidate)
        except Exception:
            continue

    if dataset_path is not None:
        raise FileNotFoundError(f"VJBench dataset JSON not found: {dataset_path}")

    raise FileNotFoundError("VJBench dataset JSON not found. Set VJBENCH_DATASET_JSON or pass --dataset_path.")


class VJBenchDatasetLoader:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = find_vjbench_dataset_path(dataset_path) if dataset_path is None else str(Path(dataset_path).expanduser())
        self._dataset: Optional[Dict[str, dict]] = None

    def load(self) -> Dict[str, dict]:
        if self._dataset is not None:
            return self._dataset

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            raise ValueError("VJBench dataset JSON must be a dict")

        dataset: Dict[str, dict] = {}
        for key, entry in raw.items():
            config = _normalize_case(str(key), entry)
            dataset[config["vuln_id"]] = config

        if len(dataset) == 0:
            raise ValueError(f"No VJBench cases found in {self.dataset_path}")

        self._dataset = dataset
        return self._dataset

    def get(self, vuln_id: str) -> dict:
        dataset = self.load()
        if vuln_id not in dataset:
            raise KeyError(f"VJBench instance not found: {vuln_id}")
        return dict(dataset[vuln_id])

    def iter_configs(self) -> Generator[dict, None, None]:
        for config in self.load().values():
            yield dict(config)

    def list_instances(self) -> list[str]:
        return sorted(self.load().keys())

    def list_projects(self) -> list[str]:
        return sorted({self.project_name(config) for config in self.load().values()})

    @staticmethod
    def project_name(config: dict) -> str:
        return _normalize_project_name(config.get("instance_id"), config)
