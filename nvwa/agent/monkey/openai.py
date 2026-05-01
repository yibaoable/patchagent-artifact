import random
import time

import openai
import httpx

from langchain_core.agents import AgentAction, AgentFinish
from langchain.agents import AgentExecutor
from langchain_openai import ChatOpenAI
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents.format_scratchpad.openai_tools import format_to_openai_tool_messages

from nvwa.logger import log
from nvwa.agent.base import BaseAgent
from nvwa.context import Context, ContextManager
from nvwa.proxy.default import create_locate_tool, create_validate_tool, create_viewcode_tool
from nvwa.agent.monkey.prompt import (
    get_monkey_system_prompt,
    MONKEY_USER_PROMPT_TEMPLATE,
    MONKEY_USER_PROMPT_TEMPLATE_SINGLE_SHOT,
)


class RetryingChatOpenAI(ChatOpenAI):
    SINGLE_CALL_MAX_RETRIES = 3
    SINGLE_CALL_BASE_DELAY_SECONDS = 1.0
    SINGLE_CALL_JITTER_SECONDS = 0.25
    TOOL_TURN_ORDER_ERROR_MARKER = "function response turn comes immediately after a function call turn"

    def _tool_message_name(self, message) -> str | None:
        name = getattr(message, "name", None)
        if name:
            return name

        additional_kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            return additional_kwargs.get("name")
        return None

    def _summarize_tool_message_payload(self, message_dict: dict) -> str:
        content = str(message_dict.get("content", "")).replace("\n", "\\n")
        if len(content) > 120:
            content = content[:117] + "..."
        return (
            f"name={message_dict.get('name')!r} "
            f"tool_call_id={message_dict.get('tool_call_id')!r} "
            f"content_preview={content!r}"
        )

    def _tool_call_ids(self, message_dict: dict) -> list[str]:
        tool_calls = message_dict.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            return []
        ids = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_id = tool_call.get("id")
            if tool_call_id is not None:
                ids.append(str(tool_call_id))
        return ids

    def _truncate_message_content(self, content, limit: int = 120) -> str:
        text = str(content).replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _summarize_message_dict(self, index: int, message_dict: dict) -> str:
        return (
            f"message_dict[{index}] "
            f"role={message_dict.get('role')!r} "
            f"name={message_dict.get('name')!r} "
            f"tool_call_id={message_dict.get('tool_call_id')!r} "
            f"tool_calls={self._tool_call_ids(message_dict)!r} "
            f"content={self._truncate_message_content(message_dict.get('content', ''))!r}"
        )

    def _log_message_dict_dump(self, message_dicts: list[dict], reason: str):
        for index, message_dict in enumerate(message_dicts):
            log.error(self._summarize_message_dict(index, message_dict))
        log.error(
            f"{self.__class__.__name__} full message_dict dump for {reason}: "
            f"{message_dicts!r}"
        )

    def _should_dump_message_dicts_for_error(self, exc: Exception) -> bool:
        return self.TOOL_TURN_ORDER_ERROR_MARKER in str(exc).lower()

    def _create_message_dicts(self, messages, stop):
        message_dicts, params = super()._create_message_dicts(messages, stop)
        rewritten_message_dicts = []
        tool_summaries = []

        for message, message_dict in zip(messages, message_dicts):
            if message_dict.get("role") != "tool":
                rewritten_message_dicts.append(message_dict)
                continue

            tool_name = self._tool_message_name(message)
            if tool_name:
                message_dict = {**message_dict, "name": tool_name}
                tool_summaries.append(self._summarize_tool_message_payload(message_dict))
            else:
                log.warning(
                    f"{self.__class__.__name__} encountered tool message without name; "
                    f"tool_call_id={message_dict.get('tool_call_id')!r}"
                )

            rewritten_message_dicts.append(message_dict)

        if tool_summaries:
            log.info(
                f"{self.__class__.__name__} prepared tool payloads: "
                + " | ".join(tool_summaries)
            )

        return rewritten_message_dicts, params

    def _classify_retry_error(self, exc: Exception) -> str:
        transient_errors = (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
            httpx.RemoteProtocolError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
        )
        request_or_logic_errors = (
            openai.BadRequestError,
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
            openai.ConflictError,
            openai.UnprocessableEntityError,
        )

        if isinstance(exc, transient_errors):
            return "transient_api"
        if isinstance(exc, request_or_logic_errors):
            return "request_or_logic"
        return "unknown"

    def _retry_delay_seconds(self, retry_index: int) -> float:
        delay = self.SINGLE_CALL_BASE_DELAY_SECONDS * (2**retry_index)
        return delay + random.uniform(0.0, self.SINGLE_CALL_JITTER_SECONDS)

    def _truncate_exception_text(self, exc: Exception, limit: int = 300) -> str:
        text = str(exc).replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _single_call_retry_warning(self, operation: str, exc: Exception, attempt: int, total_attempts: int, delay: float):
        category = self._classify_retry_error(exc)
        log.warning(
            f"{self.__class__.__name__} {operation} failed with {type(exc).__name__} "
            f"({category}) on attempt {attempt}/{total_attempts}; "
            f"error={self._truncate_exception_text(exc)!r}; retrying in {delay:.2f}s"
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        total_attempts = self.SINGLE_CALL_MAX_RETRIES + 1
        for attempt in range(1, total_attempts + 1):
            try:
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                if self._should_dump_message_dicts_for_error(exc):
                    message_dicts, _ = self._create_message_dicts(messages, stop)
                    self._log_message_dict_dump(message_dicts, reason="tool turn ordering")
                if attempt == total_attempts:
                    raise
                delay = self._retry_delay_seconds(attempt - 1)
                self._single_call_retry_warning("generate", exc, attempt, total_attempts, delay)
                time.sleep(delay)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        total_attempts = self.SINGLE_CALL_MAX_RETRIES + 1
        for attempt in range(1, total_attempts + 1):
            yielded = False
            try:
                for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                    yielded = True
                    yield chunk
                return
            except Exception as exc:
                if self._should_dump_message_dicts_for_error(exc):
                    message_dicts, _ = self._create_message_dicts(messages, stop)
                    self._log_message_dict_dump(message_dicts, reason="tool turn ordering")
                if yielded or attempt == total_attempts:
                    raise
                delay = self._retry_delay_seconds(attempt - 1)
                self._single_call_retry_warning("stream", exc, attempt, total_attempts, delay)
                time.sleep(delay)


class MonkeyOpenAIAgent(BaseAgent):
    def __init__(
        self,
        context_manager: ContextManager,
        model: str = "gpt-4-0125-preview",
        temperature: float = 1,
        auto_hint: bool = False,
        counterexample_num: int = 3,
        locate_tool: bool = True,
        max_iterations: int = 30,
        single_shot_validate: bool = False,
    ):
        super().__init__(context_manager)

        self.model = model
        self.temperature = temperature
        self.auto_hint = auto_hint
        self.counterexample_num = counterexample_num
        self.locate_tool = locate_tool
        self.max_iterations = max_iterations
        self.single_shot_validate = single_shot_validate
        self.error_cases = self.get_previous_error_cases()

        self.llm = RetryingChatOpenAI(temperature=self.temperature, model=self.model, max_retries=0)

    def _context_debug_summary(self, context: Context) -> str:
        try:
            shape = context.message_shape_summary()
        except Exception:
            shape = "unavailable"

        try:
            tools = context.tool_call_debug_summary()
        except Exception:
            tools = "unavailable"

        return f"message_shape={shape} recent_tools={tools}"

    def setup(self, context: Context):
        issue_summary = getattr(context.task, "issue_summary")
        issue_kind = getattr(context.task, "issue_kind", "bug context")

        context.single_shot_validate = self.single_shot_validate

        lc_tools = [
            create_viewcode_tool(context, auto_hint=self.auto_hint),
            create_validate_tool(
                context,
                auto_hint=self.auto_hint,
                return_direct=self.single_shot_validate,
            ),
        ]
        if self.locate_tool:
            lc_tools.append(create_locate_tool(context, auto_hint=self.auto_hint))
        oai_tools = [convert_to_openai_tool(tool) for tool in lc_tools]

        system_prompt = get_monkey_system_prompt(getattr(context.task, "language", ""))
        # ChatPromptTemplate treats `{}` as template variables; escape braces in static system prompt examples.
        escaped_system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")
        user_prompt_template = (
            MONKEY_USER_PROMPT_TEMPLATE_SINGLE_SHOT if self.single_shot_validate else MONKEY_USER_PROMPT_TEMPLATE
        )

        if self.locate_tool:
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", escaped_system_prompt),
                    ("user", user_prompt_template),
                    MessagesPlaceholder(variable_name="agent_scratchpad"),
                ]
            )
            context.add_system_message(system_prompt)
        else:
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    ("user", user_prompt_template),
                    MessagesPlaceholder(variable_name="agent_scratchpad"),
                ]
            )

        context.add_user_message(
            user_prompt_template.format(
                project=context.task.project,
                tag=context.task.tag,
                issue=issue_summary,
                issue_kind=issue_kind,
                error_cases=self.error_cases,
            )
        )

        self.llm_with_tool = self.llm.bind_tools(tools=oai_tools)
        
        def save_agent_output(output):
            if isinstance(output, AgentFinish):
                log.info(
                    f"{self.__class__.__name__} received AgentFinish "
                    f"log_preview={output.log[:200]!r} {self._context_debug_summary(context)}"
                )
                context.add_llm_response(output.log)
            else:
                if not isinstance(output, list):
                    log.error(f"Invalid output: {output} {self._context_debug_summary(context)}")
                else:
                    for action in output:
                        if isinstance(action, AgentAction):
                            log.info(
                                f"{self.__class__.__name__} received AgentAction "
                                f"log_preview={action.log[:200]!r} {self._context_debug_summary(context)}"
                            )
                            context.add_llm_response(action.log)
                        else:
                            log.error(f"Invalid action: {action} {self._context_debug_summary(context)}")

            return output

        self.agent = (
            {
                "project": lambda input: context.task.project,
                "tag": lambda input: context.task.tag,
                "issue": lambda input: issue_summary,
                "issue_kind": lambda input: issue_kind,
                "error_cases": lambda input: self.error_cases,
                "agent_scratchpad": lambda input: format_to_openai_tool_messages(input["intermediate_steps"]),
            }
            | self.prompt
            | self.llm_with_tool
            | OpenAIToolsAgentOutputParser()
            | save_agent_output
        )

        self.agent_executor = AgentExecutor(agent=self.agent, tools=lc_tools, verbose=True, max_iterations=self.max_iterations)  # type: ignore

    def get_previous_error_cases(self):
        error_cases = []
        for context in self.context_manager.contexts:
            for tool_call in context.tool_calls:
                if tool_call["name"] == "validate":
                    error_cases.append(f"Error case: \n{tool_call['args']['patch']}")

        error_cases = random.sample(error_cases, min(self.counterexample_num, len(error_cases)))
        if len(error_cases) == 0:
            return ""

        hint = "Here are some wrong patches you generated previously, you CAN NOT use them again:\n"
        error_message = hint + "\n".join(error_cases)
        log.purple(f"[{self.__class__.__name__}] Error cases: \n" + error_message)
        return error_message

    def _apply(self):
        log.info(
            f"Applying {self.__class__.__name__} (model: {self.model}, temperature: {self.temperature}, auto_hint: {self.auto_hint}, counterexample_num: {self.counterexample_num}, locate_tool: {self.locate_tool}, single_shot_validate: {self.single_shot_validate})"
        )

        with self.context_manager.new_context() as context:
            self.setup(context)
            log.info(f"{self.__class__.__name__} invoking agent executor {self._context_debug_summary(context)}")
            _ = self.agent_executor.invoke({})
