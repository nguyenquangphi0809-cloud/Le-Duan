"""Bảng giá và công thức chi phí: token suy luận, giờ máy chủ, tốc độ đốt tiền, runway."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from .money import D, ZERO

MILLION = Decimal(1_000_000)

# Giá USD / 1 triệu token (Anthropic API, cập nhật 2026-09). Có thể lệch thực tế; hoá đơn
# thật xem tại console.anthropic.com. cache_write ≈ 1.25× input, cache_read theo bảng.
MODEL_PRICES: dict[str, dict[str, Decimal]] = {
    "claude-opus-5-5":   {"input": D(4),  "output": D(20), "cache_write": D(5),     "cache_read": D("0.20")},
    "claude-opus-5":     {"input": D(5),  "output": D(25), "cache_write": D("6.25"), "cache_read": D("0.50")},
    "claude-opus-4-8":   {"input": D(5),  "output": D(25), "cache_write": D("6.25"), "cache_read": D("0.50")},
    "claude-opus-4-7":   {"input": D(5),  "output": D(25), "cache_write": D("6.25"), "cache_read": D("0.50")},
    "claude-opus-4-6":   {"input": D(5),  "output": D(25), "cache_write": D("6.25"), "cache_read": D("0.50")},
    "claude-sonnet-5-5": {"input": D(2),  "output": D(10), "cache_write": D("2.50"), "cache_read": D("0.20")},
    "claude-sonnet-5":   {"input": D(2),  "output": D(10), "cache_write": D("2.50"), "cache_read": D("0.20")},
    "claude-sonnet-4-6": {"input": D(3),  "output": D(15), "cache_write": D("3.75"), "cache_read": D("0.30")},
    "claude-haiku-4-5":  {"input": D(1),  "output": D(5),  "cache_write": D("1.25"), "cache_read": D("0.10")},
    "claude-fable-5-1":  {"input": D(10), "output": D(50), "cache_write": D("12.50"), "cache_read": D("0.25")},
    "claude-fable-5":    {"input": D(10), "output": D(50), "cache_write": D("12.50"), "cache_read": D("0.25")},
}
DEFAULT_PRICE = MODEL_PRICES["claude-opus-5-5"]


def price_for(model: str) -> dict[str, Decimal]:
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    # khớp theo tiền tố (ví dụ tên có hậu tố ngày)
    for key, price in MODEL_PRICES.items():
        if model.startswith(key):
            return price
    return DEFAULT_PRICE


def inference_cost(model: str, usage: dict[str, Any]) -> Decimal:
    """usage: input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens."""
    p = price_for(model)
    inp = Decimal(int(usage.get("input_tokens") or 0))
    out = Decimal(int(usage.get("output_tokens") or 0))
    cw = Decimal(int(usage.get("cache_creation_input_tokens") or 0))
    cr = Decimal(int(usage.get("cache_read_input_tokens") or 0))
    cost = (inp * p["input"] + out * p["output"] + cw * p["cache_write"] + cr * p["cache_read"]) / MILLION
    return D(cost)


def server_cost(usd_per_hour, seconds: float) -> Decimal:
    if seconds <= 0:
        return ZERO
    return D(D(usd_per_hour) * Decimal(seconds) / Decimal(3600))


def burn_rate_per_day(ledger, now: float, born_at: Optional[float], window_seconds: int = 86400) -> Decimal:
    """Chi phí vận hành trung bình mỗi ngày trong cửa sổ gần nhất (co lại nếu mới sinh)."""
    start = now - window_seconds
    effective_window = float(window_seconds)
    if born_at is not None and born_at > start:
        start = born_at
        effective_window = max(now - born_at, 1.0)
    spent = ledger.costs_since(start)
    if effective_window < 3600:  # dưới 1 giờ: chưa đủ dữ liệu, dùng cửa sổ 1 giờ
        effective_window = 3600.0
    return D(spent * Decimal(86400) / Decimal(effective_window))


def runway_days(balance: Decimal, burn_per_day: Decimal) -> Optional[Decimal]:
    if burn_per_day <= ZERO:
        return None  # chưa đốt gì -> vô hạn
    return D(balance / burn_per_day)
