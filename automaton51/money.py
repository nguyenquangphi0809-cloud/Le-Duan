"""Tiền tệ: dùng Decimal với 6 chữ số thập phân (micro-USD) để không mất xu lẻ."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, getcontext

getcontext().prec = 28

QUANT = Decimal("0.000001")
ZERO = Decimal("0")


def D(value) -> Decimal:
    """Chuyển int/float/str/Decimal thành Decimal đã làm tròn 6 chữ số."""
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, float):
        d = Decimal(repr(value))
    else:
        d = Decimal(str(value))
    return d.quantize(QUANT, rounding=ROUND_HALF_UP)


def floor6(value: Decimal) -> Decimal:
    """Làm tròn XUỐNG 6 chữ số (dùng khi chia lợi nhuận để phần chủ sở hữu >= 51%)."""
    return Decimal(value).quantize(QUANT, rounding=ROUND_DOWN)


def fmt(value, places: int = 2, symbol: str = "$") -> str:
    d = D(value)
    q = Decimal(1).scaleb(-places)
    return f"{symbol}{d.quantize(q, rounding=ROUND_HALF_UP):,}"


def fmt6(value, symbol: str = "$") -> str:
    return f"{symbol}{D(value):f}"
