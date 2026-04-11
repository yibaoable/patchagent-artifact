from typing import Optional

from nvwa.vul4j_runtime import prepare_vul4j_immutable_dir, validate_vul4j_patch_v2
from nvwa.sky.vuln_func_task import VulnFuncTask
from skyset.skyset_tools.vul4j_loader import Vul4JDatasetLoader


class Vul4JTask(VulnFuncTask):
    dataset_name = "vul4j"
    dataset_label = "Vul4J"
    host_env_prefix = "VUL4J"
    removed_source_paths = ("VUL4J",)

    @classmethod
    def case_id(cls, config: dict) -> str:
        return str(config["vul_id"])

    @classmethod
    def project_name(cls, config: dict) -> str:
        return Vul4JDatasetLoader.project_name(config)

    @classmethod
    def from_dataset(cls, case_id: str, dataset_path: Optional[str] = None, **kwargs) -> "Vul4JTask":
        loader = Vul4JDatasetLoader(dataset_path)
        return cls(loader.get(case_id), dataset_path=loader.dataset_path, **kwargs)

    def _description(self) -> str:
        return str(self.config.get("cve_description") or "")

    def _locations(self) -> list[str]:
        file_path = str(self.config.get("buggy_file") or "")
        locations = []

        for start, end in self.config.get("buggy_method_with_comment") or []:
            locations.append(f"{file_path}:{start}-{end}")

        for lines in self.config.get("buggy_line") or []:
            if len(lines) == 0:
                continue
            line = lines[0]
            locations.append(f"{file_path}:{line}-{line}")

        return list(dict.fromkeys(locations))

    def _prepare_container_immutable(self) -> tuple[bool, str]:
        return prepare_vul4j_immutable_dir(self.tag, self.immutable_project_path, remove_vul4j_dir=True)

    def _validate_patch(self, patch_text: str) -> tuple[bool, str]:
        return validate_vul4j_patch_v2(
            vuln_id=self.tag,
            patch_text=patch_text,
            container_name=self.container_name,
            work_dir=self.immutable_project_path,
            validate_dir=self.validate_project_path,
        )
