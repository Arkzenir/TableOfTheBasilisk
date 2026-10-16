"""The normalised agent interface (ARCHITECTURE §3.3, §4.1). Implement per provider in P1.

Tool schemas come from `basilisk.kernel.tools.generate()`; adapters translate
them to each provider's format and validate every call before it reaches the
engine (unknown tool, malformed arguments, free values where strict settings
require enums, nonexistent ids with fuzzy repair).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Kind = Literal["in_character", "rules_query", "banter", "react", "table_talk"]
Urgency = Literal["interrupt", "normal", "can_wait"]


@dataclass(frozen=True)
class Bid:
    """Stage 2 discretionary bid (§4.1). `one_line_intent` is <= 20 words and is shown on the overlay."""
    want_floor: int
    kind: Kind
    target: str | None
    urgency: Urgency
    one_line_intent: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ActResult:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    refused: bool = False


class AgentAdapter(ABC):
    """bid / act / recap / prep - the whole contract between the orchestrator and a model."""

    provider: str
    model: str

    @abstractmethod
    def bid(self, context: str, timeout_ms: int = 800) -> Bid | None:
        """Cheap-tier bid. Return None on timeout; the scheduler falls back to deterministic bids (§4.2)."""

    @abstractmethod
    def act(self, context: str, tools: dict[str, dict], token_budget: int) -> ActResult:
        """Full generation with tools. Validate and repair tool calls before returning (§7.5)."""

    @abstractmethod
    def recap(self, context: str) -> str:
        """Session recap from a player's perspective (§6.3)."""

    @abstractmethod
    def prep(self, context: str, tools: dict[str, dict]) -> ActResult:
        """GM prep pass (§7.6)."""
