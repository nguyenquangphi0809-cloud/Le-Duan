"""Thanh toán: tạo mã QR VietQR cho từng đơn, dò tiền về qua SePay, khớp theo mã đơn trong nội dung chuyển khoản.

Chỉ giao dịch CÓ MÃ ĐƠN mới được coi là doanh thu kinh doanh. Tiền khác về tài khoản (cá nhân)
bị bỏ qua hoàn toàn và không được ghi vào sổ cái.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

SEPAY_LIST_URL = "https://my.sepay.vn/userapi/transactions/list"


@dataclass
class BankTransaction:
    id: str
    amount_vnd: int
    content: str
    account_number: str = ""
    when: str = ""
    reference: str = ""
    direction: str = "in"


class PaymentSource(Protocol):
    def fetch(self) -> list[BankTransaction]: ...


def vietqr_url(bank_id: str, account_number: str, account_name: str, amount_vnd: int, add_info: str,
               template: str = "compact2") -> str:
    """Liên kết ảnh QR chuẩn VietQR (img.vietqr.io): quét bằng mọi ứng dụng ngân hàng, tự điền số tiền và nội dung."""
    q = urllib.parse.urlencode({"amount": int(amount_vnd), "addInfo": add_info, "accountName": account_name})
    return f"https://img.vietqr.io/image/{urllib.parse.quote(bank_id)}-{urllib.parse.quote(account_number)}-{template}.png?{q}"


def normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def find_code(content: str, codes: list[str]) -> Optional[str]:
    norm = normalize(content)
    for code in sorted(codes, key=len, reverse=True):
        if normalize(code) and normalize(code) in norm:
            return code
    return None


def _to_int_vnd(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().replace(",", "")
    try:
        return int(round(float(text)))
    except ValueError:
        return 0


def parse_sepay_list(payload: dict) -> list[BankTransaction]:
    """Phân tích phản hồi GET /userapi/transactions/list (chịu được khác biệt nhỏ về tên trường)."""
    rows = payload.get("transactions") or payload.get("data") or []
    out: list[BankTransaction] = []
    for r in rows:
        amount_in = _to_int_vnd(r.get("amount_in", r.get("transferAmount")))
        amount_out = _to_int_vnd(r.get("amount_out", 0))
        direction = str(r.get("transferType") or ("in" if amount_in > 0 else "out"))
        if direction != "in" or amount_in <= 0 or amount_out > 0:
            continue
        out.append(BankTransaction(
            id=f"sepay:{r.get('id')}", amount_vnd=amount_in,
            content=str(r.get("transaction_content") or r.get("content") or r.get("description") or ""),
            account_number=str(r.get("account_number") or r.get("accountNumber") or ""),
            when=str(r.get("transaction_date") or r.get("transactionDate") or ""),
            reference=str(r.get("reference_number") or r.get("referenceCode") or "")))
    return out


def parse_sepay_webhook(body: dict) -> Optional[BankTransaction]:
    """Webhook SePay: {id, gateway, transactionDate, accountNumber, content, transferType, transferAmount, referenceCode, ...}"""
    if str(body.get("transferType", "in")) != "in":
        return None
    amount = _to_int_vnd(body.get("transferAmount"))
    if amount <= 0:
        return None
    return BankTransaction(id=f"sepay:{body.get('id')}", amount_vnd=amount,
                           content=str(body.get("content") or body.get("description") or ""),
                           account_number=str(body.get("accountNumber") or ""),
                           when=str(body.get("transactionDate") or ""), reference=str(body.get("referenceCode") or ""))


class SePaySource:
    def __init__(self, api_token: str, account_number: str = "", limit: int = 50,
                 http_get: Optional[Callable[[str, dict], dict]] = None):
        self.token = api_token
        self.account = account_number
        self.limit = limit
        self.http_get = http_get or _http_get_json

    def fetch(self) -> list[BankTransaction]:
        params = {"limit": self.limit}
        if self.account:
            params["account_number"] = self.account
        url = SEPAY_LIST_URL + "?" + urllib.parse.urlencode(params)
        data = self.http_get(url, {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        return parse_sepay_list(data)


class InboxSource:
    """Giao dịch do webhook SePay đẩy vào (server.py ghi vào payments_inbox.jsonl)."""

    def __init__(self, read_rows: Callable[[], list[dict]]):
        self.read_rows = read_rows

    def fetch(self) -> list[BankTransaction]:
        out = []
        for row in self.read_rows():
            tx = parse_sepay_webhook(row)
            if tx:
                out.append(tx)
        return out


class FakePaymentSource:
    def __init__(self):
        self.transactions: list[BankTransaction] = []

    def add(self, amount_vnd: int, content: str, tx_id: str = "") -> BankTransaction:
        tx = BankTransaction(id=tx_id or f"fake:{len(self.transactions) + 1}", amount_vnd=int(amount_vnd), content=content)
        self.transactions.append(tx)
        return tx

    def fetch(self) -> list[BankTransaction]:
        return list(self.transactions)


def _http_get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "automaton51/0.2", **headers})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))
