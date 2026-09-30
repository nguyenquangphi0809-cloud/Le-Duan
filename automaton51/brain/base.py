"""Giao diện 'bộ não': mỗi lượt gồm nhiều bước; mỗi bước trả văn bản + các lệnh gọi công cụ + usage token."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class BrainError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class BrainStep:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    stop_reason: str = "end_turn"
    error: str = ""


class Brain:
    name = "base"

    def set_model(self, model: str, effort: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def begin_turn(self, system: str, turn_input: str, tools: list[dict[str, Any]], context: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    def step(self, tool_results: Optional[list[dict[str, Any]]]) -> BrainStep:  # pragma: no cover
        raise NotImplementedError
