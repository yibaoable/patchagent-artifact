from typing import Union
from nvwa.sky.task import PatchTask
from nvwa.policy.default import DefaultPolicy

from nvwa.logger import log


def patch(
    task: PatchTask,
    reset: bool = True,
    model: str = "gpt-4",
    log_path: Union[None, str] = None,
    max_iteration: int = -1,
    single_shot_validate: bool = False,
) -> Union[None, str]:
    """Run patching agents. When ``single_shot_validate`` is True, the first ``validate`` call
    ends that agent turn (no further LLM steps) and ``task.patch`` is set to that patch even if
    validation fails. Each ``validate`` is recorded on the context as ``patch_validation_results``.

    With ``DefaultPolicy``, the first agent always leaves ``task.patch`` set under single-shot mode,
    so later agents are skipped unless you pass ``max_iteration=1`` (only one agent) intentionally
    or rely on the first agent being your sole attempt.
    """
    log.info(f"Start Patching {task} (reset={reset}, single_shot_validate={single_shot_validate})")

    policy = DefaultPolicy(
        task,
        reset=reset,
        model=model,
        log_path=log_path,
        single_shot_validate=single_shot_validate,
    )
    policy.apply(max_iteration=max_iteration)

    return task.patch
