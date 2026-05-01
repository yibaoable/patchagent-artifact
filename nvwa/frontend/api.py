from typing import Union
from nvwa.sky.task import PatchTask
from nvwa.policy.default import DefaultPolicy

from nvwa.logger import log, attach_case_file_handler, detach_case_file_handler


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
    case_handler = attach_case_file_handler(task, model)

    try:
        policy = DefaultPolicy(
            task,
            reset=reset,
            model=model,
            log_path=log_path,
            single_shot_validate=single_shot_validate,
        )
        default_attempts = DefaultPolicy.default_agent_attempt_count()
        effective_attempts = default_attempts if max_iteration < 0 else min(default_attempts, max_iteration)
        log.info(
            f"DefaultPolicy configured for {default_attempts} sequential agent attempts; "
            f"this run will execute up to {effective_attempts}. "
            "Dataset runtime containers may be reused across validate calls when supported by the runtime."
        )
        policy.apply(max_iteration=max_iteration)
    finally:
        detach_case_file_handler(case_handler)

    return task.patch
