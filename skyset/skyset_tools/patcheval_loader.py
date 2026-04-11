import json
import os

from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
PATCHEVAL_MARKERS = ("cve_id", "repo", "programming_language", "vul_func")
SUPPORTED_LANGUAGES = {"python", "javascript", "go"}


def _default_container_name(instance_id: str) -> str:
    prefix = os.getenv("PATCHEVAL_IMAGE_PREFIX", "ghcr.io/anonymous2578-data")
    return f"{prefix}/{instance_id.lower()}" if prefix else instance_id


def _normalize_container_name(container_name: str) -> str:
    return str(container_name).strip().lower()


def _normalize_project_name(config: dict) -> str:
    if config.get("project_name"):
        return str(config["project_name"])

    repo = str(config.get("repo") or "").rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo:
        return repo.rsplit("/", 1)[-1].lower()

    return str(config.get("cve_id") or config.get("instance_id") or "")


def _normalize_language(config: dict) -> str:
    language = str(config.get("programming_language") or config.get("language") or "").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported Patcheval language: {language or '<empty>'}")
    return language


def _looks_like_patcheval_config(key: Optional[str], config: dict) -> bool:
    if any(marker in config for marker in PATCHEVAL_MARKERS):
        return True
    if config.get("cve_id"):
        return True
    return key is not None and key.upper().startswith("CVE-")


def _normalize_case(key: Optional[str], raw_case: dict) -> dict:
    if not isinstance(raw_case, dict):
        raise ValueError("Patcheval dataset entries must be JSON objects")

    case = dict(raw_case)
    if not _looks_like_patcheval_config(key, case):
        raise ValueError("Not a Patcheval dataset entry")

    if not case.get("cve_id"):
        if key is None:
            raise ValueError("Patcheval dataset entry is missing cve_id")
        case["cve_id"] = key

    case["cve_id"] = str(case["cve_id"])
    case["instance_id"] = case["cve_id"]
    case["project_name"] = _normalize_project_name(case)
    case["container_name"] = _normalize_container_name(case.get("container_name") or _default_container_name(case["cve_id"]))
    case["work_dir"] = str(case.get("work_dir") or os.path.join("/workspace", case["project_name"]))
    case["dataset"] = "patcheval"
    case["input_mode"] = "vuln_func"
    case["language"] = _normalize_language(case)
    return case


def _candidate_dataset_paths() -> Iterable[Path]:
    env_path = os.getenv("PATCHEVAL_DATASET_JSON")
    if env_path:
        yield Path(env_path).expanduser()

    for name in (
        "patcheval_dataset.json",
    ):
        yield REPO_ROOT / "skyset" / name


def find_patcheval_dataset_path(dataset_path: Optional[str] = None) -> str:
    candidates = [Path(dataset_path).expanduser()] if dataset_path else []
    candidates.extend(_candidate_dataset_paths())

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loader = PatchevalDatasetLoader(str(candidate))
            loader.load()
            return str(candidate)
        except Exception:
            continue

    if dataset_path is not None:
        raise FileNotFoundError(f"Patcheval dataset JSON not found: {dataset_path}")

    raise FileNotFoundError("Patcheval dataset JSON not found. Set PATCHEVAL_DATASET_JSON or pass --dataset_path.")


class PatchevalDatasetLoader:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = find_patcheval_dataset_path(dataset_path) if dataset_path is None else str(Path(dataset_path).expanduser())
        self._dataset: Optional[Dict[str, dict]] = None

    def load(self) -> Dict[str, dict]:
        if self._dataset is not None:
            return self._dataset

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, list):
            raise ValueError("Patcheval dataset JSON must be a list")

        dataset: Dict[str, dict] = {}
        for entry in raw:
            config = _normalize_case(None, entry)
            dataset[config["cve_id"]] = config

        if len(dataset) == 0:
            raise ValueError(f"No Patcheval cases found in {self.dataset_path}")

        self._dataset = dataset
        return self._dataset

    def get(self, instance_id: str) -> dict:
        dataset = self.load()
        if instance_id not in dataset:
            raise KeyError(f"Patcheval instance not found: {instance_id}")
        return dict(dataset[instance_id])

    def iter_configs(self) -> Generator[dict, None, None]:
        for config in self.load().values():
            yield dict(config)

    def list_instances(self) -> list[str]:
        return sorted(self.load().keys())

    def list_projects(self) -> list[str]:
        return sorted({self.project_name(config) for config in self.load().values()})

    @staticmethod
    def project_name(config: dict) -> str:
        return _normalize_project_name(config)

    @staticmethod
    def has_poc_test_cmd(config: dict) -> bool:
        value = config.get("poc_test_cmd")
        return isinstance(value, str) and bool(value.strip())
