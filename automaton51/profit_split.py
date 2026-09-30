"""Chia lợi nhuận 51/49 theo nguyên tắc mốc nước cao (high-water mark).

  lợi nhuận ròng tới nay   = tổng doanh thu thực − tổng chi phí vận hành thực
  phần có thể chia         = lợi nhuận ròng tới nay − phần đã chia trước đó
  nếu phần có thể chia > 0 : 49% -> quỹ mở rộng (làm tròn XUỐNG),
                             51% + phần lẻ -> quỹ chủ sở hữu.
  nếu <= 0 (đang lỗ)       : không chia; lỗ phải được bù bằng doanh thu tương lai.

Vốn mồi của chủ sở hữu không phải doanh thu nên không bao giờ bị "chia".
Chi từ quỹ mở rộng (nhân bản, marketing...) là tiền của doanh nghiệp nên không
làm giảm lợi nhuận tính cho chủ sở hữu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .constitution import OWNER_SHARE, GROWTH_SHARE
from .ledger import Ledger, Entry
from .money import D, ZERO, floor6

MIN_SETTLE = D("0.000001")


@dataclass
class Settlement:
    distributable: Decimal
    owner_amount: Decimal
    growth_amount: Decimal
    entries: list[Entry] = field(default_factory=list)

    @property
    def owner_ratio(self) -> Decimal:
        return (self.owner_amount / self.distributable) if self.distributable else ZERO


def net_profit_to_date(ledger: Ledger) -> Decimal:
    t = ledger.totals()
    return t["revenue"] - t["operating_costs"]


def distributable_profit(ledger: Ledger) -> Decimal:
    t = ledger.totals()
    return t["revenue"] - t["operating_costs"] - t["distributed"]


def split_amounts(distributable: Decimal) -> tuple[Decimal, Decimal]:
    """(owner, growth). Bảo đảm owner >= 51% và owner + growth == distributable."""
    distributable = D(distributable)
    growth = floor6(distributable * GROWTH_SHARE)
    owner = distributable - growth
    assert owner + growth == distributable
    assert owner >= floor6(distributable * OWNER_SHARE)
    return owner, growth


def settle(ledger: Ledger, memo: str = "") -> Optional[Settlement]:
    """Chia phần lợi nhuận chưa chia (nếu có). Trả None nếu không có gì để chia."""
    ledger.reload()
    d = distributable_profit(ledger)
    cap = ledger.balance("operating")  # không bao giờ chia quá số tiền đang có
    if cap < d:
        d = cap
    if d < MIN_SETTLE:
        return None
    owner, growth = split_amounts(d)
    entries = ledger.split(d, owner, growth, memo or "Chia lợi nhuận ròng: 51% chủ sở hữu / 49% quỹ mở rộng",
                           meta={"owner_share": str(OWNER_SHARE), "growth_share": str(GROWTH_SHARE)})
    return Settlement(distributable=d, owner_amount=owner, growth_amount=growth, entries=entries)
