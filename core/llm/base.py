"""Provider abstraction. Stage code NEVER imports a provider SDK directly.

See .claude/skills/grounded-extraction/SKILL.md for why: every prompt must be
runnable on the local provider, and the local-vs-cloud comparison has to be
empirical rather than a matter of opinion.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | list[dict[str, Any]]  # list form carries images for the VLM


@dataclass(frozen=True)
class LLMResult:
    text: str
    parsed: Any | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResult: ...


class ProviderUnavailable(RuntimeError):
    """Transient. The failover chain should try the next provider."""


def get_provider(name: str | None = None) -> LLMProvider:
    raise NotImplementedError("TODO(phase2): ollama, nim, anthropic, openai + failover")
