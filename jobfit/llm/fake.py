from collections import deque
from collections.abc import Sequence

from pydantic import BaseModel

from jobfit.llm.protocol import ModelT, TokenUsage


class FakeLLMClient:
    def __init__(self, responses: Sequence[tuple[BaseModel, TokenUsage]]) -> None:
        self._responses = deque(responses)
        self.call_count = 0
        self.calls: list[tuple[str, str, type[BaseModel]]] = []

    def parse(
        self,
        system: str,
        user: str,
        schema: type[ModelT],
    ) -> tuple[ModelT, TokenUsage]:
        self.call_count += 1
        self.calls.append((system, user, schema))
        if not self._responses:
            raise AssertionError("FakeLLMClient has no queued response")
        response, usage = self._responses.popleft()
        if not isinstance(response, schema):
            raise AssertionError(
                f"Expected {schema.__name__}, got {type(response).__name__}"
            )
        return response, usage
