"""Sổ cái ba ví, chỉ ghi thêm, nối băm SHA-256.

Ví:
  operating — ví vận hành: trả mọi chi phí, nhận mọi doanh thu, nhận vốn mồi.
  owner     — quỹ chủ sở hữu (51%): CHỈ được nạp bởi chia lợi nhuận; CHỈ chủ rút (payout).
  growth    — quỹ mở rộng (49%): chỉ chi cho nhân bản/marketing/nâng cấp/cứu sinh.

Bất biến được thực thi trong mã:
  * không số dư nào âm;
  * owner chỉ tăng bằng `split`, chỉ giảm bằng `payout`;
  * growth chỉ giảm bằng `growth_spend` (loại cho phép) hoặc `rescue`;
  * mỗi dòng có hash = sha256(prev_hash + nội dung) -> sửa một dòng là lộ.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .money import D, ZERO
from .state import file_lock

ACCOUNTS = ("operating", "owner", "growth")
GROWTH_CATEGORIES = frozenset({"replication", "marketing", "capacity", "rescue"})
COST_CATEGORIES = frozenset({"inference", "server", "tool", "marketing", "capacity", "other"})
GENESIS_HASH = "0" * 64


class LedgerError(Exception):
    pass


class InsufficientFunds(LedgerError):
    pass


class ProtectedAccount(LedgerError):
    pass


@dataclass
class Entry:
    seq: int
    ts: float
    txn: str
    kind: str
    account: str
    amount: Decimal
    category: str
    memo: str
    meta: dict[str, Any] = field(default_factory=dict)
    balances: dict[str, str] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def to_json(self) -> str:
        d = asdict(self)
        d["amount"] = f"{self.amount:f}"
        return json.dumps(d, ensure_ascii=False, sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entry":
        return cls(
            seq=int(d["seq"]), ts=float(d["ts"]), txn=str(d["txn"]), kind=str(d["kind"]),
            account=str(d["account"]), amount=D(d["amount"]), category=str(d.get("category", "")),
            memo=str(d.get("memo", "")), meta=dict(d.get("meta") or {}),
            balances=dict(d.get("balances") or {}), prev_hash=str(d.get("prev_hash", GENESIS_HASH)),
            hash=str(d.get("hash", "")),
        )


def _entry_hash(prev_hash: str, entry: Entry) -> str:
    d = asdict(entry)
    d.pop("hash", None)
    d["amount"] = f"{entry.amount:f}"
    payload = json.dumps(d, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: Path | str, clock: Optional[Callable[[], float]] = None, lock_path: Path | None = None):
        self.path = Path(path)
        self.clock = clock or time.time
        self.lock_path = lock_path or self.path.with_name(".ledger.lock")
        self._entries: list[Entry] = []
        self._balances: dict[str, Decimal] = {a: ZERO for a in ACCOUNTS}
        self._offset = 0
        self._last_hash = GENESIS_HASH
        self._sync()

    # ------------------------------------------------------------ đọc
    def _sync(self) -> None:
        """Nạp các dòng mới do tiến trình khác ghi thêm (CLI fund/revenue...)."""
        if not self.path.exists():
            return
        with open(self.path, "rb") as fh:
            fh.seek(self._offset)
            data = fh.read()
        if not data:
            return
        end = data.rfind(b"\n")
        if end < 0:
            return  # dòng cuối chưa hoàn chỉnh, đợi lần sau
        complete = data[: end + 1]
        for raw in complete.split(b"\n"):
            if raw:
                self._apply(Entry.from_dict(json.loads(raw.decode("utf-8"))))
        self._offset += len(complete)

    def _apply(self, entry: Entry) -> None:
        self._entries.append(entry)
        self._balances[entry.account] = self._balances.get(entry.account, ZERO) + entry.amount
        self._last_hash = entry.hash or self._last_hash

    def reload(self) -> None:
        self._sync()

    @property
    def entries(self) -> list[Entry]:
        return list(self._entries)

    def tail(self, n: int = 20) -> list[Entry]:
        return self._entries[-n:]

    def balance(self, account: str) -> Decimal:
        return self._balances.get(account, ZERO)

    def balances(self) -> dict[str, Decimal]:
        return {a: self._balances.get(a, ZERO) for a in ACCOUNTS}

    @property
    def seq(self) -> int:
        return self._entries[-1].seq if self._entries else 0

    # ------------------------------------------------------------ ghi
    def _write(self, drafts: list[dict[str, Any]]) -> list[Entry]:
        """Ghi một giao dịch (1..n dòng) nguyên tử dưới khoá tệp."""
        with file_lock(self.lock_path):
            self._sync()  # nạp thay đổi từ tiến trình khác trước khi ghi
            # kiểm tra số dư trước (toàn bộ giao dịch)
            projected = dict(self._balances)
            for d in drafts:
                projected[d["account"]] = projected.get(d["account"], ZERO) + d["amount"]
                if projected[d["account"]] < ZERO:
                    raise InsufficientFunds(
                        f"Ví '{d['account']}' không đủ tiền: cần {(-d['amount']):f}, có {self._balances.get(d['account'], ZERO):f}"
                    )
            txn = uuid.uuid4().hex[:12]
            ts = float(self.clock())
            written: list[Entry] = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                for d in drafts:
                    seq = self.seq + 1
                    running = dict(self._balances)
                    running[d["account"]] = running.get(d["account"], ZERO) + d["amount"]
                    entry = Entry(
                        seq=seq, ts=ts, txn=txn, kind=d["kind"], account=d["account"],
                        amount=D(d["amount"]), category=d.get("category", ""), memo=d.get("memo", ""),
                        meta=dict(d.get("meta") or {}),
                        balances={a: f"{running.get(a, ZERO):f}" for a in ACCOUNTS},
                        prev_hash=self._last_hash,
                    )
                    entry.hash = _entry_hash(self._last_hash, entry)
                    line = entry.to_json() + "\n"
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
                    self._apply(entry)
                    self._offset += len(line.encode("utf-8"))
                    written.append(entry)
            return written

    # ---- các loại giao dịch ----
    def deposit(self, amount, memo: str = "", meta: dict | None = None) -> Entry:
        amount = D(amount)
        if amount <= ZERO:
            raise LedgerError("Số tiền nạp phải > 0")
        return self._write([{"kind": "deposit", "account": "operating", "amount": amount,
                             "category": "capital", "memo": memo, "meta": meta}])[0]

    def revenue(self, amount, source: str, memo: str = "", meta: dict | None = None) -> Entry:
        amount = D(amount)
        if amount <= ZERO:
            raise LedgerError("Doanh thu phải > 0")
        m = dict(meta or {}); m["source"] = source
        return self._write([{"kind": "revenue", "account": "operating", "amount": amount,
                             "category": "revenue", "memo": memo, "meta": m}])[0]

    def charge(self, amount, category: str, memo: str = "", meta: dict | None = None) -> Optional[Entry]:
        amount = D(amount)
        if amount < ZERO:
            raise LedgerError("Chi phí không được âm")
        if category not in COST_CATEGORIES:
            raise LedgerError(f"Loại chi phí không hợp lệ: {category}")
        if amount == ZERO:
            return None  # không ghi dòng 0 tiền cho chi phí
        return self._write([{"kind": "cost", "account": "operating", "amount": -amount,
                             "category": category, "memo": memo, "meta": meta}])[0]

    def split(self, distributable, owner_amount, growth_amount, memo: str = "", meta: dict | None = None) -> list[Entry]:
        distributable, owner_amount, growth_amount = D(distributable), D(owner_amount), D(growth_amount)
        if owner_amount + growth_amount != distributable:
            raise LedgerError("owner + growth phải bằng đúng phần chia")
        if distributable <= ZERO:
            raise LedgerError("Phần chia phải > 0")
        return self._write([
            {"kind": "split", "account": "operating", "amount": -distributable, "category": "profit", "memo": memo, "meta": meta},
            {"kind": "split", "account": "owner", "amount": owner_amount, "category": "profit_51", "memo": memo, "meta": meta},
            {"kind": "split", "account": "growth", "amount": growth_amount, "category": "profit_49", "memo": memo, "meta": meta},
        ])

    def growth_spend(self, amount, category: str, memo: str = "", meta: dict | None = None) -> Entry:
        amount = D(amount)
        if category not in GROWTH_CATEGORIES:
            raise ProtectedAccount(f"Quỹ mở rộng chỉ chi cho {sorted(GROWTH_CATEGORIES)}, không phải '{category}'")
        if amount <= ZERO:
            raise LedgerError("Số tiền chi phải > 0")
        return self._write([{"kind": "growth_spend", "account": "growth", "amount": -amount,
                             "category": category, "memo": memo, "meta": meta}])[0]

    def rescue(self, amount, memo: str = "Cứu sinh: quỹ mở rộng -> ví vận hành", meta: dict | None = None) -> list[Entry]:
        amount = D(amount)
        if amount <= ZERO:
            raise LedgerError("Số tiền cứu sinh phải > 0")
        return self._write([
            {"kind": "rescue", "account": "growth", "amount": -amount, "category": "rescue", "memo": memo, "meta": meta},
            {"kind": "rescue", "account": "operating", "amount": amount, "category": "rescue", "memo": memo, "meta": meta},
        ])

    def payout(self, amount, memo: str = "Chủ sở hữu rút 51%", meta: dict | None = None) -> Entry:
        amount = D(amount)
        if amount <= ZERO:
            raise LedgerError("Số tiền rút phải > 0")
        return self._write([{"kind": "payout", "account": "owner", "amount": -amount,
                             "category": "payout", "memo": memo, "meta": meta}])[0]

    def withdraw(self, amount, memo: str = "Chủ sở hữu rút vốn vận hành", meta: dict | None = None) -> Entry:
        amount = D(amount)
        if amount <= ZERO:
            raise LedgerError("Số tiền rút phải > 0")
        return self._write([{"kind": "withdraw", "account": "operating", "amount": -amount,
                             "category": "capital", "memo": memo, "meta": meta}])[0]

    def note(self, kind: str, memo: str, meta: dict | None = None) -> Entry:
        """Dòng 0 tiền để ghi sự kiện (khai sinh, chết, đổi tầng...)."""
        return self._write([{"kind": kind, "account": "operating", "amount": ZERO,
                             "category": "event", "memo": memo, "meta": meta}])[0]

    # ------------------------------------------------------------ thống kê
    def totals(self) -> dict[str, Decimal]:
        t = {k: ZERO for k in (
            "deposits", "withdrawn", "revenue", "operating_costs", "distributed",
            "owner_received", "growth_received", "owner_paid_out", "growth_spent", "rescued",
            "inference_costs", "server_costs", "tool_costs")}
        for e in self._entries:
            k, a, amt = e.kind, e.account, e.amount
            if k == "deposit": t["deposits"] += amt
            elif k == "withdraw": t["withdrawn"] += -amt
            elif k == "revenue": t["revenue"] += amt
            elif k == "cost":
                t["operating_costs"] += -amt
                if e.category == "inference": t["inference_costs"] += -amt
                elif e.category == "server": t["server_costs"] += -amt
                elif e.category == "tool": t["tool_costs"] += -amt
            elif k == "split":
                if a == "operating": t["distributed"] += -amt
                elif a == "owner": t["owner_received"] += amt
                elif a == "growth": t["growth_received"] += amt
            elif k == "growth_spend": t["growth_spent"] += -amt
            elif k == "rescue" and a == "growth": t["rescued"] += -amt
            elif k == "payout": t["owner_paid_out"] += -amt
        return t

    def costs_since(self, ts: float, category: str | None = None) -> Decimal:
        total = ZERO
        for e in reversed(self._entries):
            if e.ts < ts:
                break
            if e.kind == "cost" and (category is None or e.category == category):
                total += -e.amount
        return total

    def revenue_since(self, ts: float) -> Decimal:
        total = ZERO
        for e in reversed(self._entries):
            if e.ts < ts:
                break
            if e.kind == "revenue":
                total += e.amount
        return total

    def verify_chain(self) -> tuple[bool, str]:
        prev = GENESIS_HASH
        balances = {a: ZERO for a in ACCOUNTS}
        for e in self._entries:
            if e.prev_hash != prev:
                return False, f"dòng {e.seq}: prev_hash không khớp"
            if _entry_hash(prev, e) != e.hash:
                return False, f"dòng {e.seq}: hash sai (nội dung đã bị sửa)"
            balances[e.account] = balances.get(e.account, ZERO) + e.amount
            if balances[e.account] < ZERO:
                return False, f"dòng {e.seq}: số dư âm"
            if e.account == "owner" and e.kind not in ("split", "payout"):
                return False, f"dòng {e.seq}: quỹ chủ sở hữu bị ghi bởi loại '{e.kind}'"
            if e.account == "growth" and e.kind not in ("split", "growth_spend", "rescue"):
                return False, f"dòng {e.seq}: quỹ mở rộng bị ghi bởi loại '{e.kind}'"
            prev = e.hash
        return True, "ok"
