import json
import os

from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
VUL4J_MARKERS = ("vul_id", "buggy_file", "cve_description", "project")


def _split_case_list(raw: Optional[str]) -> set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _use_latest_image(vuln_id: str) -> bool:
    return vuln_id in _split_case_list(os.getenv("VUL4J_LATEST_CASES"))


def _default_container_name(vuln_id: str) -> str:
    if _use_latest_image(vuln_id):
        return os.getenv("VUL4J_IMAGE_LATEST", "bqcuongas/vul4j:latest")
    return os.getenv("VUL4J_IMAGE_ALLDEPS", "bqcuongas/vul4j:alldeps")


def _default_work_dir(vuln_id: str) -> str:
    work_root = os.getenv("VUL4J_WORK_ROOT", "/tmp/vul4j")
    return os.path.join(work_root, vuln_id)


def _normalize_project_name(config: dict) -> str:
    if config.get("project_name"):
        return str(config["project_name"])
    if config.get("project"):
        return str(config["project"])
    vuln_id = str(config.get("vul_id", ""))
    if "-" in vuln_id:
        return vuln_id.split("-", 1)[0]
    return vuln_id


def _looks_like_vul4j_config(key: Optional[str], config: dict) -> bool:
    if any(marker in config for marker in VUL4J_MARKERS):
        return True
    if config.get("vul_id"):
        return True
    if key is None:
        return False
    return key.upper().startswith("VUL4J-")


def _normalize_case(key: Optional[str], raw_case: dict) -> dict:
    if not isinstance(raw_case, dict):
        raise ValueError("Vul4J dataset entries must be JSON objects")

    case = dict(raw_case)
    if not _looks_like_vul4j_config(key, case):
        raise ValueError("Not a Vul4J dataset entry")

    if not case.get("vul_id"):
        if key is None:
            raise ValueError("Vul4J dataset entry is missing vul_id")
        case["vul_id"] = key

    case["vul_id"] = str(case["vul_id"])
    case["instance_id"] = case["vul_id"]
    case["project_name"] = _normalize_project_name(case)
    case.setdefault("container_name", _default_container_name(case["vul_id"]))
    case.setdefault("work_dir", _default_work_dir(case["vul_id"]))
    case.setdefault("dataset", "vul4j")
    case["input_mode"] = "vuln_func"
    return case


def _candidate_dataset_paths() -> Iterable[Path]:
    env_path = os.getenv("VUL4J_DATASET_JSON")
    if env_path:
        yield Path(env_path).expanduser()

    for name in (
        "vul4j_dataset.json",
    ):
        yield REPO_ROOT / "skyset" / name


def find_vul4j_dataset_path(dataset_path: Optional[str] = None) -> str:
    candidates = [Path(dataset_path).expanduser()] if dataset_path else []
    candidates.extend(_candidate_dataset_paths())

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loader = Vul4JDatasetLoader(str(candidate))
            loader.load()
            return str(candidate)
        except Exception:
            continue

    if dataset_path is not None:
        raise FileNotFoundError(f"Vul4J dataset JSON not found: {dataset_path}")

    raise FileNotFoundError("Vul4J dataset JSON not found. Set VUL4J_DATASET_JSON or pass --dataset_path.")


class Vul4JDatasetLoader:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = find_vul4j_dataset_path(dataset_path) if dataset_path is None else str(Path(dataset_path).expanduser())
        self._dataset: Optional[Dict[str, dict]] = None

    def load(self) -> Dict[str, dict]:
        if self._dataset is not None:
            return self._dataset

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, list):
            raise ValueError("Vul4J dataset JSON must be a list")

        dataset: Dict[str, dict] = {}
        for entry in raw:
            config = _normalize_case(None, entry)
            dataset[config["vul_id"]] = config

        if len(dataset) == 0:
            raise ValueError(f"No Vul4J cases found in {self.dataset_path}")

        self._dataset = dataset
        return self._dataset

    def get(self, vuln_id: str) -> dict:
        dataset = self.load()
        if vuln_id not in dataset:
            raise KeyError(f"Vul4J instance not found: {vuln_id}")
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
        return _normalize_project_name(config)
