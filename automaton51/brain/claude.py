"""Bộ não thật: Claude qua Anthropic SDK (Messages API, tool use, adaptive thinking).

Thiết kế theo tài liệu SDK Python (anthropic >= 1.x):
  * vòng lặp tác nhân thủ công (để tính tiền từng lời gọi API và kiểm tra sinh tồn giữa các bước)
  * prompt caching: system ổn định + cache_control; nội dung động nằm ở tin nhắn user đầu lượt
  * thinking adaptive + output_config.effort theo tầng sinh tồn (Haiku 4.5: không dùng effort)
  * strict tool schemas; fallbacks server-side (server-side-fallback-2026-07-01) khi model hỗ trợ
  * xử lý stop_reason: tool_use / end_turn / max_tokens / refusal / pause_turn
"""
from __future__ import annotations

from typing import Any, Optional

from .base import Brain, BrainError, BrainStep, ToolCall

FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5")
PAUSE_TURN_RESTARTS = 3


class ClaudeBrain(Brain):
    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "high", max_tokens: int = 16000,
                 enable_fallbacks: bool = True, client: Any = None):
        try:
            import anthropic  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise BrainError("Chưa cài SDK: pip install anthropic") from exc
        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.enable_fallbacks = enable_fallbacks
        self._system: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []
        self._tools: list[dict[str, Any]] = []

    def set_model(self, model: str, effort: str) -> None:
        self.model, self.effort = model, effort

    def begin_turn(self, system: str, turn_input: str, tools: list[dict[str, Any]], context: dict[str, Any]) -> None:
        # Phần system ổn định qua các lượt -> cache; phần động (số dư, tầng...) đi trong tin nhắn user.
        self._system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        self._tools = list(tools)
        self._messages = [{"role": "user", "content": turn_input}]

    # ---- request ----
    def _request_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._system,
            "messages": self._messages,
            "tools": self._tools,
        }
        if not self.model.startswith("claude-haiku"):
            kw["thinking"] = {"type": "adaptive"}
            kw["output_config"] = {"effort": self.effort}
        if self.enable_fallbacks and any(self.model.startswith(m) for m in FALLBACK_MODELS):
            kw["betas"] = ["server-side-fallback-2026-07-01"]
            kw["fallbacks"] = "default"
        return kw

    def _create(self) -> Any:
        a = self._anthropic
        kw = self._request_kwargs()
        try:
            return self.client.beta.messages.create(**kw)
        except (TypeError, a.BadRequestError) as exc:
            msg = str(exc)
            if ("fallbacks" in kw) and ("fallback" in msg.lower() or "beta" in msg.lower() or isinstance(exc, TypeError)):
                # SDK/khu vực không hỗ trợ fallbacks -> tắt và thử lại một lần
                self.enable_fallbacks = False
                kw.pop("fallbacks", None)
                kw.pop("betas", None)
                return self.client.beta.messages.create(**kw)
            raise

    @staticmethod
    def _usage(resp: Any) -> dict[str, int]:
        u = getattr(resp, "usage", None)
        return {
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        }

    def step(self, tool_results: Optional[list[dict[str, Any]]]) -> BrainStep:
        a = self._anthropic
        if tool_results:
            self._messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"], "is_error": bool(r.get("is_error"))}
                for r in tool_results]})
        usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        served_model = self.model
        restarts = 0
        while True:
            try:
                resp = self._create()
            except a.AuthenticationError as exc:
                raise BrainError("API key không hợp lệ. Đặt ANTHROPIC_API_KEY (hoặc `ant auth login`).") from exc
            except a.RateLimitError as exc:
                return BrainStep(error=f"Bị giới hạn tốc độ (429): {exc}", usage=usage_total, model=served_model, stop_reason="error")
            except a.APIStatusError as exc:
                return BrainStep(error=f"Lỗi API {exc.status_code}: {getattr(exc, 'message', exc)}", usage=usage_total, model=served_model, stop_reason="error")
            except a.APIConnectionError as exc:
                return BrainStep(error=f"Lỗi mạng khi gọi API: {exc}", usage=usage_total, model=served_model, stop_reason="error")
            u = self._usage(resp)
            for k in usage_total:
                usage_total[k] += u[k]
            served_model = getattr(resp, "model", None) or self.model
            # luôn nối nguyên content (kể cả thinking blocks) để lượt sau hợp lệ
            self._messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "pause_turn" and restarts < PAUSE_TURN_RESTARTS:
                restarts += 1
                continue
            break

        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        calls = [ToolCall(id=b.id, name=b.name, input=dict(b.input or {}))
                 for b in resp.content if getattr(b, "type", "") == "tool_use"]
        stop = resp.stop_reason or "end_turn"
        error = ""
        if stop == "refusal":
            details = getattr(resp, "stop_details", None)
            error = f"Model từ chối (an toàn): {getattr(details, 'category', None)} — {getattr(details, 'explanation', '')}"
            calls = []
        elif stop == "max_tokens":
            error = "Hết max_tokens giữa chừng; bỏ qua các lệnh công cụ chưa hoàn chỉnh."
            calls = []
        return BrainStep(text=text, tool_calls=calls, usage=usage_total, model=served_model, stop_reason=stop, error=error)
