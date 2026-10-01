from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    def parse(
        self,
        system: str,
        user: str,
        schema: type[ModelT],
    ) -> tuple[ModelT, TokenUsage]: ...
