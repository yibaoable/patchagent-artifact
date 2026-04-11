from abc import ABC, abstractmethod
from typing import Iterator, Union

from nvwa.agent.base import BaseAgent
from nvwa.context import ContextManager
from nvwa.sky.task import PatchTask


class BasePolicy(ABC):
    def __init__(self, task: PatchTask, reset: bool = False, log_path: Union[None, str] = None, model: str = "gpt-4"):
        self.task: PatchTask = task
        self.agent_generator: Iterator[BaseAgent] = self._agent_generator()
        self.context_manager: ContextManager = ContextManager(task, load_context=not reset, path=log_path, model=model)

    @abstractmethod
    def _agent_generator(self) -> Iterator[BaseAgent]:
        pass

    def apply(self, max_iteration: int = -1):
        for agent in self.agent_generator:
            if max_iteration == 0:
                break
            agent.apply()
            max_iteration -= 1
        self.context_manager.save()
