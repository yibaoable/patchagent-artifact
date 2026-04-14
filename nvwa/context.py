import os
import time
import json
from typing import Any, Dict, List, Union, Optional

try:
    import tiktoken
except ImportError:
    tiktoken = None

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
        # Token usage statistics
        self.token_usage: Optional[Dict[str, int]] = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_time = time.time() - self.start_time
        
    @property
    def tool_calls(self):
        return [message["message"] for message in self.messages if message["role"] == "tool"]

    def calculate_token_usage(self, model: str = "gpt-4-turbo") -> Dict[str, int]:
        """Calculate token usage for this context based on messages.
        
        Returns:
            Dict with keys 'input_tokens', 'output_tokens', 'total_tokens'
        """
        if not self.messages or tiktoken is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        
        try:
            encoder = tiktoken.encoding_for_model(model)
        except Exception:
            # Fallback to gpt-4-turbo encoding if model not found
            try:
                encoder = tiktoken.encoding_for_model("gpt-4-turbo")
            except Exception:
                return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        
        input_tokens = 0
        output_tokens = 0
        
        # First two messages are system and user prompts
        if len(self.messages) >= 2:
            for i in range(2):
                if self.messages[i]["role"] in ["system", "user"]:
                    input_tokens += len(encoder.encode(self.messages[i]["message"]))
        
        # Process remaining messages
        for i in range(2, len(self.messages)):
            message = self.messages[i]
            role = message["role"]
            
            if role == "ai":
                output_tokens += len(encoder.encode(message["message"]))
            elif role == "tool":
                # Tool results are part of input for next turn
                tool_result = message["message"].get("result", "")
                input_tokens += len(encoder.encode(tool_result))
        
        total_tokens = input_tokens + output_tokens
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

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
        # Calculate token usage if not already done
        if self.token_usage is None:
            self.token_usage = self.calculate_token_usage()
        
        return {
            "patch": self.patch,
            "elapsed_time": self.elapsed_time,
            "messages": self.messages,
            "single_shot_validate": self.single_shot_validate,
            "patch_validation_results": list(self.patch_validation_results),
            "token_usage": self.token_usage,
        }

    def load(self, data: dict):
        self.patch = data.get("patch", None)
        self.elapsed_time = data.get("elapsed_time", None)
        self.messages = data.get("messages", [])
        self.single_shot_validate = bool(data.get("single_shot_validate", False))
        self.patch_validation_results = list(data.get("patch_validation_results", []))
        self.token_usage = data.get("token_usage", None)
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
            # Handle both old format (array) and new format (dict with summary)
            if isinstance(json_data, dict) and "contexts" in json_data:
                contexts_data = json_data.get("contexts", [])
            elif isinstance(json_data, list):
                contexts_data = json_data
            else:
                log.warning(f"Unexpected JSON format in {path}")
                return
            
            for data in contexts_data:
                context = Context(self.task)
                context.load(data)
                self.contexts.append(context)

    def save(self, path: Union[str, None] = None):
        path = path or self.path
        log.info(f"Saving contexts to {path}")
        data = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        
        for context in self.contexts:
            c = context.dump()
            if len(c['messages']) > 2: # HACK: it means critical error happened
                data.append(c)
                # Accumulate token usage
                if c.get('token_usage'):
                    total_input_tokens += c['token_usage'].get('input_tokens', 0)
                    total_output_tokens += c['token_usage'].get('output_tokens', 0)
                    total_tokens += c['token_usage'].get('total_tokens', 0)
        
        if len(data) > 0:
            # Add summary statistics at the top level
            summary = {
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
                "num_attempts": len(data),
                "contexts": data,
            }
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(summary, f, indent=4)
            log.info(f"Token usage summary: input={total_input_tokens}, output={total_output_tokens}, total={total_tokens}")

    @property
    def elapsed_time(self):
        return sum(context.elapsed_time for context in self.contexts if context.elapsed_time is not None)

    @property
    def count(self):
        return len(self.contexts)
