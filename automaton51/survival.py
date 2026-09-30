"""Tầng sinh tồn: normal -> low_compute -> critical -> dead.

Ví vận hành = 0 không chết ngay: có thời gian ân hạn (mặc định 1 giờ) để chủ sở hữu
nạp tiền hoặc quỹ mở rộng cứu. Hết ân hạn mà vẫn 0 -> DEAD, hệ thống dừng vĩnh viễn.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

from .money import D, ZERO


class Tier(str, Enum):
    NORMAL = "normal"
    LOW = "low_compute"
    CRITICAL = "critical"
    DEAD = "dead"


@dataclass
class SurvivalStatus:
    tier: Tier
    previous: Optional[Tier]
    changed: bool
    balance: Decimal
    zero_since: Optional[float]
    seconds_to_death: Optional[float]

    @property
    def alive(self) -> bool:
        return self.tier != Tier.DEAD


def tier_for_balance(balance: Decimal, low_threshold: Decimal, critical_threshold: Decimal) -> Tier:
    if balance > low_threshold:
        return Tier.NORMAL
    if balance > critical_threshold:
        return Tier.LOW
    return Tier.CRITICAL


class SurvivalMonitor:
    """Theo dõi tầng; trạng thái (tầng hiện tại, thời điểm về 0) được lưu qua kv."""

    def __init__(self, low_threshold, critical_threshold, dead_grace_seconds: int,
                 kv_get: Callable[[str, object], object], kv_set: Callable[[str, object], None]):
        self.low = D(low_threshold)
        self.critical = D(critical_threshold)
        self.grace = int(dead_grace_seconds)
        self._get = kv_get
        self._set = kv_set

    def current(self) -> Optional[Tier]:
        raw = self._get("survival_tier", None)
        return Tier(raw) if raw else None

    def evaluate(self, balance, now: float) -> SurvivalStatus:
        balance = D(balance)
        previous = self.current()
        if previous == Tier.DEAD:
            return SurvivalStatus(Tier.DEAD, previous, False, balance, self._get("zero_since", None), 0.0)  # type: ignore[arg-type]

        zero_since = self._get("zero_since", None)
        tier = tier_for_balance(balance, self.low, self.critical)
        seconds_to_death: Optional[float] = None
        if balance <= ZERO:
            if zero_since is None:
                zero_since = float(now)
                self._set("zero_since", zero_since)
            elapsed = float(now) - float(zero_since)
            seconds_to_death = max(0.0, self.grace - elapsed)
            if elapsed >= self.grace:
                tier = Tier.DEAD
        else:
            if zero_since is not None:
                self._set("zero_since", None)
                zero_since = None

        changed = previous != tier
        if changed:
            self._set("survival_tier", tier.value)
        return SurvivalStatus(tier, previous, changed, balance, zero_since, seconds_to_death)  # type: ignore[arg-type]
