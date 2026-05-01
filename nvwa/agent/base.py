import openai
import httpx
import random
import time
import traceback

from abc import ABC, abstractmethod
from nvwa.context import ContextManager
from nvwa.logger import log


class BaseAgent(ABC):
    MAX_APPLY_RETRIES = 3
    BASE_RETRY_DELAY_SECONDS = 1.0
    RETRY_JITTER_SECONDS = 0.25

    def __init__(self, context_manager: ContextManager):
        self.context_manager: ContextManager = context_manager

    @abstractmethod
    def _apply(self):
        pass

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
        delay = self.BASE_RETRY_DELAY_SECONDS * (2**retry_index)
        return delay + random.uniform(0.0, self.RETRY_JITTER_SECONDS)

    def _latest_context_debug_suffix(self) -> str:
        contexts = getattr(self.context_manager, "contexts", [])
        if len(contexts) == 0:
            return "message_shape=<none> recent_tools=<none>"

        context = contexts[-1]
        shape = "unavailable"
        tools = "unavailable"
        if hasattr(context, "message_shape_summary"):
            try:
                shape = context.message_shape_summary()
            except Exception:
                shape = "error"
        if hasattr(context, "tool_call_debug_summary"):
            try:
                tools = context.tool_call_debug_summary()
            except Exception:
                tools = "error"
        return f"message_shape={shape} recent_tools={tools}"

    def _truncate_exception_text(self, exc: Exception, limit: int = 300) -> str:
        text = str(exc).replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _looks_like_tool_serialization_issue(self, exc: Exception) -> bool:
        message = str(exc)
        markers = (
            "function_response.name",
            "REQUIRED_FIELD_MISSING",
            "upstream_error",
            "GenerateContentRequest proto is invalid",
        )
        return any(marker in message for marker in markers)

    def _log_final_error(self, exc: Exception, category: str, attempts: int):
        if isinstance(exc, openai.APIError):
            message = f"OpenAI API error after {attempts} attempts ({category}): {exc}"
        elif isinstance(exc, httpx.HTTPError):
            message = f"HTTPX error after {attempts} attempts ({category}): {exc}"
        else:
            message = f"Unknown Error after {attempts} attempts ({category}): {exc}"

        log.error(message)
        log.error(f"Error context: {self._latest_context_debug_suffix()}")
        if self._looks_like_tool_serialization_issue(exc):
            log.error("Likely tool-response serialization issue")
        log.error(traceback.format_exc())

    def apply(self):
        if self.context_manager.patch is not None:
            return
        log.info(f"Applying {self.__class__.__name__}")

        total_attempts = self.MAX_APPLY_RETRIES + 1
        for attempt in range(1, total_attempts + 1):
            try:
                self._apply()
                return
            except Exception as e:
                category = self._classify_retry_error(e)
                if attempt == total_attempts:
                    self._log_final_error(e, category, total_attempts)
                    return

                delay = self._retry_delay_seconds(attempt - 1)
                log.warning(
                    f"{self.__class__.__name__} failed with {type(e).__name__} "
                    f"({category}) on attempt {attempt}/{total_attempts}; "
                    f"error={self._truncate_exception_text(e)!r}; "
                    f"{self._latest_context_debug_suffix()}; "
                    f"retrying in {delay:.2f}s"
                )
                if self._looks_like_tool_serialization_issue(e):
                    log.warning("Likely tool-response serialization issue")
                time.sleep(delay)
