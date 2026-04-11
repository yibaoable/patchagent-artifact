import json
import os

from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
SECBENCH_MARKERS = ("instance_id", "work_dir", "bug_description", "repo", "base_commit")


def _default_container_name(instance_id: str) -> str:
    prefix = os.getenv("SECBENCH_CONTAINER_PREFIX", "hwiwonlee/secb.eval.x86_64")
    return f"{prefix}.{instance_id}" if prefix else instance_id


def _normalize_project_name(config: dict) -> str:
    if config.get("project_name"):
        return str(config["project_name"])
    if config.get("project"):
        return str(config["project"])
    if config.get("repo") and "/" in str(config["repo"]):
        return str(config["repo"]).split("/", 1)[0]
    instance_id = str(config.get("instance_id", ""))
    if ".cve-" in instance_id:
        return instance_id.split(".cve-", 1)[0]
    if "." in instance_id:
        return instance_id.split(".", 1)[0]
    return instance_id


def _looks_like_secbench_config(key: Optional[str], config: dict) -> bool:
    if any(marker in config for marker in SECBENCH_MARKERS):
        return True
    if config.get("instance_id"):
        return True
    if key is None:
        return False
    return ".cve-" in key.lower() or key.count(".") >= 1


def _normalize_case(key: Optional[str], raw_case: dict) -> dict:
    if not isinstance(raw_case, dict):
        raise ValueError("SEC-bench dataset entries must be JSON objects")

    case = dict(raw_case)
    if not _looks_like_secbench_config(key, case):
        raise ValueError("Not a SEC-bench dataset entry")

    if not case.get("instance_id"):
        if key is None:
            raise ValueError("SEC-bench dataset entry is missing instance_id")
        case["instance_id"] = key

    case["instance_id"] = str(case["instance_id"])
    case["project_name"] = _normalize_project_name(case)
    case.setdefault("container_name", _default_container_name(case["instance_id"]))
    case.setdefault("dataset", "secbench")
    return case


def _candidate_dataset_paths() -> Iterable[Path]:
    env_path = os.getenv("SECBENCH_DATASET_JSON")
    if env_path:
        yield Path(env_path).expanduser()

    for name in (
        "secbench_dataset.json",
    ):
        yield REPO_ROOT / name
        yield REPO_ROOT / "skyset" / name


def find_secb_dataset_path(dataset_path: Optional[str] = None) -> str:
    candidates = [Path(dataset_path).expanduser()] if dataset_path else []
    candidates.extend(_candidate_dataset_paths())

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loader = SecbDatasetLoader(str(candidate))
            loader.load()
            return str(candidate)
        except Exception:
            continue

    if dataset_path is not None:
        raise FileNotFoundError(f"SEC-bench dataset JSON not found: {dataset_path}")

    raise FileNotFoundError(
        "SEC-bench dataset JSON not found. Set SECBENCH_DATASET_JSON or pass --dataset_path."
    )


class SecbDatasetLoader:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = find_secb_dataset_path(dataset_path) if dataset_path is None else str(Path(dataset_path).expanduser())
        self._dataset: Optional[Dict[str, dict]] = None

    def load(self) -> Dict[str, dict]:
        if self._dataset is not None:
            return self._dataset

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        dataset: Dict[str, dict] = {}
        if isinstance(raw, list):
            for entry in raw:
                config = _normalize_case(None, entry)
                dataset[config["instance_id"]] = config
        elif isinstance(raw, dict):
            for key, entry in raw.items():
                config = _normalize_case(str(key), entry)
                dataset[config["instance_id"]] = config
        else:
            raise ValueError("SEC-bench dataset JSON must be a list or dict")

        if len(dataset) == 0:
            raise ValueError(f"No SEC-bench cases found in {self.dataset_path}")

        self._dataset = dataset
        return self._dataset

    def get(self, instance_id: str) -> dict:
        dataset = self.load()
        if instance_id not in dataset:
            raise KeyError(f"SEC-bench instance not found: {instance_id}")
        return dict(dataset[instance_id])

    def iter_configs(self) -> Generator[dict, None, None]:
        for config in self.load().values():
            yield dict(config)

    def get_by_project(self, project_name: str) -> Generator[dict, None, None]:
        for config in self.iter_configs():
            if self.project_name(config) == project_name:
                yield config

    def list_instances(self) -> list[str]:
        return sorted(self.load().keys())

    def list_projects(self) -> list[str]:
        return sorted({self.project_name(config) for config in self.load().values()})

    def count(self) -> int:
        return len(self.load())

    @staticmethod
    def project_name(config: dict) -> str:
        return _normalize_project_name(config)


def list_secb_instances(dataset_path: Optional[str] = None) -> list[str]:
    return SecbDatasetLoader(dataset_path).list_instances()


def list_secb_projects(dataset_path: Optional[str] = None) -> list[str]:
    return SecbDatasetLoader(dataset_path).list_projects()
