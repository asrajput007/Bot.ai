import logging
import time
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from .errors import LLMError, LLMOutputError

log = logging.getLogger("growth_os.llm")


def _failure_reason(exc):
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "the request timed out"
    if "ratelimit" in name:
        return "the service is rate limiting requests"
    if "connection" in name:
        return "the service could not be reached"
    if "auth" in name or "permission" in name:
        return "the service rejected the server credentials"
    return "the service reported an error"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def as_dict(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 3),
        }


class LLMClient(Protocol):
    def structured(self, schema, system, user, temperature): ...


class AzureLLM:
    def __init__(self, settings):
        self._settings = settings
        self._models = {}

    def _model(self, temperature):
        if temperature not in self._models:
            s = self._settings
            self._models[temperature] = AzureChatOpenAI(
                azure_deployment=s.deployment,
                azure_endpoint=s.endpoint,
                api_key=s.api_key,
                api_version=s.api_version,
                temperature=temperature,
                timeout=s.request_timeout,
                max_retries=2,
            )
        return self._models[temperature]

    def structured(self, schema, system, user, temperature):
        runnable = self._model(temperature).with_structured_output(
            schema, method="function_calling", include_raw=True
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        usage = Usage()
        last_error = None
        for _ in range(2):
            started = time.perf_counter()
            try:
                result = runnable.invoke(messages)
            except Exception as exc:
                log.warning("AI service call failed: %s: %s", type(exc).__name__, exc)
                raise LLMError(f"The AI service could not complete the request: {_failure_reason(exc)}.") from exc
            usage.seconds += time.perf_counter() - started
            meta = getattr(result["raw"], "usage_metadata", None) or {}
            usage.input_tokens += int(meta.get("input_tokens", 0))
            usage.output_tokens += int(meta.get("output_tokens", 0))
            if result.get("parsed") is not None:
                return result["parsed"], usage
            last_error = result.get("parsing_error")
        log.warning("AI service output did not match %s: %s", schema.__name__, last_error)
        raise LLMOutputError("The AI service returned incomplete content.")
