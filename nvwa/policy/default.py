from typing import Iterator, List, Union
from nvwa.agent.base import BaseAgent
from nvwa.policy.base import BasePolicy
from nvwa.sky.task import PatchTask
from nvwa.agent.monkey import MonkeyOpenAIAgent


class DefaultPolicy(BasePolicy):
    MONKEYOPENAI_ITERATION_NUM = 3
    AGENTS_PER_TEMPERATURE = 5

    def __init__(
        self,
        task: PatchTask,
        reset: bool = False,
        model: str = "gpt-4",
        log_path: Union[None, str] = None,
        single_shot_validate: bool = False,
    ):
        super().__init__(task, reset=reset, log_path=log_path, model=model)
        self.model = model
        self.single_shot_validate = single_shot_validate
        self.agent_list: List[BaseAgent] = []

    @classmethod
    def default_agent_attempt_count(cls) -> int:
        return cls.MONKEYOPENAI_ITERATION_NUM * cls.AGENTS_PER_TEMPERATURE

    def _agent_generator(self) -> Iterator[BaseAgent]:
        ssv = self.single_shot_validate
        for i in range(self.MONKEYOPENAI_ITERATION_NUM):
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=True, counterexample_num=0, single_shot_validate=ssv)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=False, counterexample_num=0, single_shot_validate=ssv)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=True, counterexample_num=3, single_shot_validate=ssv)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=False, counterexample_num=3, single_shot_validate=ssv)

        for i in range(self.MONKEYOPENAI_ITERATION_NUM):
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), locate_tool=True, single_shot_validate=ssv)

