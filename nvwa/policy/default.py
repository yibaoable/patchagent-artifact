from typing import Iterator, List, Union
from nvwa.agent.base import BaseAgent
from nvwa.policy.base import BasePolicy
from nvwa.sky.task import PatchTask
from nvwa.agent.monkey import MonkeyOpenAIAgent


class DefaultPolicy(BasePolicy):
    MONKEYOPENAI_ITERATION_NUM = 3

    def __init__(self, task: PatchTask, reset: bool = False, model: str = "gpt-4", log_path: Union[None, str] = None):
        super().__init__(task, reset=reset, log_path=log_path, model=model)
        self.model = model
        self.agent_list: List[BaseAgent] = []

    def _agent_generator(self) -> Iterator[BaseAgent]:
        for i in range(self.MONKEYOPENAI_ITERATION_NUM):
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=True, counterexample_num=0)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=False, counterexample_num=0)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=True, counterexample_num=3)
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), auto_hint=False, counterexample_num=3)

        for i in range(self.MONKEYOPENAI_ITERATION_NUM):
            yield MonkeyOpenAIAgent(self.context_manager, model=self.model, temperature=i * (1 / (self.MONKEYOPENAI_ITERATION_NUM - 1)), locate_tool=True)

