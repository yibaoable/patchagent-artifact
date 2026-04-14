import os
import time
import json
from typing import Any, Dict, List, Union

from nvwa.model_aliases import readable_model_dirname
from nvwa.sky.task import PatchTask
from nvwa.logger import log


class Context:
    def __init__(self, task: PatchTask) -> None:
        self.task = task

        self.patch = None
        self.messages = []
        self.elapsed_time = None
        # When True, first validate ends the agent run (see MonkeyOpenAIAgent + validate tool return_direct).
        self.single_shot_validate = False
        # One entry per validate() call: revised patch text, pass/fail, report string.
        self.patch_validation_results: List[Dict[str, Any]] = []

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_time = time.time() - self.start_time
        
    @property
    def tool_calls(self):
        return [message["message"] for message in self.messages if message["role"] == "tool"]

    def add_tool_call(self, name: str, args: dict, result: str):
        self.messages.append(
            {
                "role": "tool",
                "message": {
                    "name": name,
                    "args": args,
                    "result": result,
                },
            }
        )
        if self.task.patch is not None:
            self.patch = self.task.patch

    def add_llm_response(self, response: str):
        if len(response) > 0:
            self.messages.append(
                {
                    "role": "ai",
                    "message": response,
                }
            )

    def add_system_message(self, message: str):
        if len(message) > 0:
            self.messages.append(
                {
                    "role": "system",
                    "message": message,
                }
            )

    def add_user_message(self, message: str):
        if len(message) > 0:
            self.messages.append(
                {
                    "role": "user",
                    "message": message,
                }
            )

    def dump(self):
        return {
            "patch": self.patch,
            "elapsed_time": self.elapsed_time,
            "messages": self.messages,
            "single_shot_validate": self.single_shot_validate,
            "patch_validation_results": list(self.patch_validation_results),
        }

    def load(self, data: dict):
        self.patch = data.get("patch", None)
        self.elapsed_time = data.get("elapsed_time", None)
        self.messages = data.get("messages", [])
        self.single_shot_validate = bool(data.get("single_shot_validate", False))
        self.patch_validation_results = list(data.get("patch_validation_results", []))
        if self.task.patch is None and self.patch is not None:
            self.task.patch = self.patch
            log.info(f"Task {self.task} has been patched.")


class ContextManager:
    def __init__(self, task: PatchTask, load_context: bool = False, path: Union[str, None] = None, model: str = "gpt-4") -> None:
        self.task: PatchTask = task
        self.model = model
        self.contexts: List[Context] = []
        if path is None or os.path.isfile(path):
            self._path = path
        else:
            self._path = os.path.join(path, self._result_relpath())

        if load_context:
            log.info(f"Loading contexts from {self.path}")
            self.load(self.path)

    def _result_relpath(self) -> str:
        dataset = getattr(self.task, "dataset", "skyset")
        instance_id = getattr(self.task, "instance_id", self.task.tag)
        input_mode = getattr(self.task, "input_mode", getattr(self.task, "effective_input_mode", "auto"))
        model_name = readable_model_dirname(self.model)
        return os.path.join(model_name, dataset, input_mode, f"{instance_id}.json")

    @property
    def path(self) -> str:
        if self._path:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            return self._path
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "results", self._result_relpath()))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    @property
    def patch(self) -> Union[str, None]:
        return self.task.patch

    def new_context(self) -> Context:
        context = Context(self.task)
        self.contexts.append(context)
        return context

    def load(self, path: Union[str, None] = None):
        path = path or self.path
        if os.path.exists(path):
            with open(path, "r") as f:
                json_data = json.load(f)
            for data in json_data:
                context = Context(self.task)
                context.load(data)
                self.contexts.append(context)

    def save(self, path: Union[str, None] = None):
        path = path or self.path
        log.info(f"Saving contexts to {path}")
        data = []
        for context in self.contexts:
            c = context.dump()
            if len(c['messages']) > 2: # HACK: it means critical error happened
                data.append(c)
        if len(data) > 0:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=4)

    @property
    def elapsed_time(self):
        return sum(context.elapsed_time for context in self.contexts if context.elapsed_time is not None)

    @property
    def count(self):
        return len(self.contexts)
