from typing import Optional

from nvwa.patcheval_runtime import prepare_patcheval_immutable_dir, validate_patcheval_patch_v2
from nvwa.sky.vuln_func_task import VulnFuncTask
from skyset.skyset_tools.patcheval_loader import PatchevalDatasetLoader


class PatchevalTask(VulnFuncTask):
    dataset_name = "patcheval"
    dataset_label = "Patcheval"
    host_env_prefix = "PATCHEVAL"

    @classmethod
    def case_id(cls, config: dict) -> str:
        return str(config["cve_id"])

    @classmethod
    def project_name(cls, config: dict) -> str:
        return PatchevalDatasetLoader.project_name(config)

    @classmethod
    def from_dataset(cls, case_id: str, dataset_path: Optional[str] = None, **kwargs) -> "PatchevalTask":
        loader = PatchevalDatasetLoader(dataset_path)
        return cls(loader.get(case_id), dataset_path=loader.dataset_path, **kwargs)

    @property
    def validate_project_path(self) -> str:
        return self.work_dir

    def _description(self) -> str:
        lines: list[str] = []
        description = str(self.config.get("cve_description") or "").strip()
        if description:
            lines.append(description)

        cwe_info = self.config.get("cwe_info") or {}
        if isinstance(cwe_info, dict) and cwe_info:
            lines.append("")
            lines.append("CWE information:")
            for cwe_id, details in cwe_info.items():
                detail_map = details if isinstance(details, dict) else {}
                name = str(detail_map.get("name") or "").strip()
                detail_description = str(detail_map.get("description") or "").strip()
                title = f"- {cwe_id}"
                if name:
                    title += f": {name}"
                lines.append(title)
                if detail_description:
                    lines.append(detail_description)

        return "\n".join(lines).strip()

    def _locations(self) -> list[str]:
        locations: list[str] = []
        if not self.config.get("vul_func"):
            return locations
        for entry in self.config.get("vul_func") or []:
            if not isinstance(entry, dict):
                continue
            file_path = str(entry.get("file_path") or "").strip()
            if not file_path:
                continue
            start_line = entry.get("start_line")
            end_line = entry.get("end_line")
            if isinstance(start_line, int) and isinstance(end_line, int):
                locations.append(f"{file_path}:{start_line}-{end_line}")
            elif isinstance(start_line, int):
                locations.append(f"{file_path}:{start_line}-{start_line}")
            else:
                locations.append(file_path)
        return list(dict.fromkeys(locations))

    def _prepare_container_immutable(self) -> tuple[bool, str]:
        return prepare_patcheval_immutable_dir(self.tag, self.work_dir, self.immutable_project_path)

    def _validate_patch(self, patch_text: str) -> tuple[bool, str]:
        return validate_patcheval_patch_v2(
            instance_id=self.tag,
            patch_text=patch_text,
            container_name=self.container_name,
            immutable_dir=self.immutable_project_path,
            validate_dir=self.validate_project_path,
            language=self.language,
        )
