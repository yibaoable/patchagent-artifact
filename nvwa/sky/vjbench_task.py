from typing import Optional

from nvwa.vjbench_runtime import prepare_vjbench_immutable_dir, validate_vjbench_patch_v2
from nvwa.sky.vuln_func_task import VulnFuncTask
from skyset.skyset_tools.vjbench_loader import VJBenchDatasetLoader


class VJBenchTask(VulnFuncTask):
    dataset_name = "vjbench"
    dataset_label = "VJBench"
    host_env_prefix = "VJBENCH"

    @classmethod
    def case_id(cls, config: dict) -> str:
        return str(config["vuln_id"])

    @classmethod
    def project_name(cls, config: dict) -> str:
        return VJBenchDatasetLoader.project_name(config)

    @classmethod
    def from_dataset(cls, case_id: str, dataset_path: Optional[str] = None, **kwargs) -> "VJBenchTask":
        loader = VJBenchDatasetLoader(dataset_path)
        return cls(loader.get(case_id), dataset_path=loader.dataset_path, **kwargs)

    def _description(self) -> str:
        return str(self.config.get("cve_description") or "")

    def _locations(self) -> list[str]:
        file_path = str(self.config.get("buggy_file_path") or "")
        locations = []

        for start, end in self.config.get("comment_buggy_method") or []:
            locations.append(f"{file_path}:{start}-{end}")

        for start, end in self.config.get("buggy_method") or []:
            locations.append(f"{file_path}:{start}-{end}")

        for lines in self.config.get("buggy_line") or []:
            if len(lines) == 0:
                continue
            line = lines[0]
            locations.append(f"{file_path}:{line}-{line}")

        return list(dict.fromkeys(locations))

    def _prepare_container_immutable(self) -> tuple[bool, str]:
        return prepare_vjbench_immutable_dir(self.tag, self.immutable_project_path)

    def _validate_patch(self, patch_text: str) -> tuple[bool, str]:
        return validate_vjbench_patch_v2(
            vuln_id=self.tag,
            patch_text=patch_text,
            container_name=self.container_name,
            work_dir=self.immutable_project_path,
            validate_dir=self.validate_project_path,
            skip_compile=bool(self.config.get("skip_compile_cmd")),
        )
