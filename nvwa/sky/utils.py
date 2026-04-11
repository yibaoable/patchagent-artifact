import os
import yaml
from typing import Generator

from nvwa.sky.task import ROOT, PatchTask, skyset_tools
from skyset.skyset_tools.patcheval_loader import PatchevalDatasetLoader
from skyset.skyset_tools.secb_loader import SecbDatasetLoader
from skyset.skyset_tools.vul4j_loader import Vul4JDatasetLoader
from skyset.skyset_tools.vjbench_loader import VJBenchDatasetLoader


def make_task(project: str, tag: str, dataset: str = "skyset", dataset_path: str | None = None, input_mode: str = "auto", **kwargs) -> PatchTask:
    if dataset == "patcheval":
        from nvwa.sky.patcheval_task import PatchevalTask

        return PatchevalTask.from_dataset(tag, dataset_path=dataset_path, **kwargs)
    if dataset == "secbench":
        from nvwa.sky.secb_task import SecbTask

        return SecbTask.from_dataset(tag, dataset_path=dataset_path, input_mode=input_mode, **kwargs)
    if dataset == "vul4j":
        from nvwa.sky.vul4j_task import Vul4JTask

        return Vul4JTask.from_dataset(tag, dataset_path=dataset_path, **kwargs)
    if dataset == "vjbench":
        from nvwa.sky.vjbench_task import VJBenchTask

        return VJBenchTask.from_dataset(tag, dataset_path=dataset_path, **kwargs)
    return PatchTask(project, tag, skyset_tools.get_config(project, tag)["sanitizer"], **kwargs)


def get_all_task(project=None, tag=None, skip_linux=False, skip_extractfix=False, dataset: str = "skyset", dataset_path: str | None = None, input_mode: str = "auto", **kwargs) -> Generator[PatchTask, None, None]:
    if dataset == "patcheval":
        from nvwa.sky.patcheval_task import PatchevalTask

        loader = PatchevalDatasetLoader(dataset_path)
        if tag is not None:
            config = loader.get(tag)
            yield PatchevalTask(config, dataset_path=loader.dataset_path, **kwargs)
            return

        for config in loader.iter_configs():
            if not loader.has_poc_test_cmd(config):
                continue
            if project is not None and loader.project_name(config) != project:
                continue
            yield PatchevalTask(config, dataset_path=loader.dataset_path, **kwargs)
        return
    if dataset == "secbench":
        from nvwa.sky.secb_task import SecbTask

        loader = SecbDatasetLoader(dataset_path)
        if tag is not None:
            config = loader.get(tag)
            if project is None or loader.project_name(config) == project:
                yield SecbTask(config, dataset_path=loader.dataset_path, input_mode=input_mode, **kwargs)
            return

        for config in loader.iter_configs():
            if project is not None and loader.project_name(config) != project:
                continue
            yield SecbTask(config, dataset_path=loader.dataset_path, input_mode=input_mode, **kwargs)
        return
    if dataset == "vul4j":
        from nvwa.sky.vul4j_task import Vul4JTask

        loader = Vul4JDatasetLoader(dataset_path)
        if tag is not None:
            config = loader.get(tag)
            # For dataset mode with specific tag, always yield the task regardless of project filter
            yield Vul4JTask(config, dataset_path=loader.dataset_path, **kwargs)
            return

        for config in loader.iter_configs():
            if project is not None and loader.project_name(config) != project:
                continue
            yield Vul4JTask(config, dataset_path=loader.dataset_path, **kwargs)
        return
    if dataset == "vjbench":
        from nvwa.sky.vjbench_task import VJBenchTask

        loader = VJBenchDatasetLoader(dataset_path)
        if tag is not None:
            config = loader.get(tag)
            # For dataset mode with specific tag, always yield the task regardless of project filter
            yield VJBenchTask(config, dataset_path=loader.dataset_path, **kwargs)
            return

        for config in loader.iter_configs():
            if project is not None and loader.project_name(config) != project:
                continue
            yield VJBenchTask(config, dataset_path=loader.dataset_path, **kwargs)
        return

    for project_ in os.listdir(ROOT):
        if (
            os.path.isdir(project_path := os.path.join(ROOT, project_))
            and project_ not in ["skyset_tools", ".git", "skyset_kernel_image", "patcheval", "secbench", "vul4j", "vjbench"]
            and not project_.startswith("external-")
            and (project is None or project == project_)
            and (not skip_extractfix or not project_.startswith("extractfix"))
            and (not skip_linux or not project_.startswith("linux"))
        ):
            for tag_ in os.listdir(project_path):
                if os.path.isdir(os.path.join(project_path, tag_)) and (tag is None or tag == tag_):
                    yield make_task(project_, tag_, dataset=dataset, dataset_path=dataset_path, input_mode=input_mode, **kwargs)
