"""Kho đơn hàng, bảng giá (tính bằng mã, không để AI tự đặt giá) và đếm trang tài liệu."""
from __future__ import annotations

import re
import secrets
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..state import StateDir, file_lock

SERVICES: dict[str, dict[str, Any]] = {
    "DF": {"name": "Định dạng theo mẫu trường / Thông tư", "hours": 24},
    "TK": {"name": "Chuẩn hoá tài liệu tham khảo và đối chiếu trích dẫn", "hours": 24},
    "HD": {"name": "Hiệu đính ngôn ngữ học thuật (Track Changes)", "hours": 72},
    "AB": {"name": "Tóm tắt tiếng Anh, từ khoá, thư gửi tạp chí", "hours": 24},
    "PB": {"name": "Bộ câu hỏi luyện phản biện và slide bảo vệ", "hours": 72},
}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ 0/O, 1/I dễ nhầm


def price_vnd(service: str, pages: int) -> int:
    pages = max(1, int(pages))
    if service == "DF":
        p = min(900_000, 400_000 + 5_000 * max(0, pages - 60))
    elif service == "TK":
        p = min(800_000, 300_000 + 4_000 * max(0, pages - 60))
    elif service == "HD":
        p = max(500_000, 25_000 * pages)
    elif service == "AB":
        p = 450_000
    elif service == "PB":
        p = min(1_500_000, 900_000 + 3_000 * max(0, pages - 80))
    else:
        raise ValueError(f"Dịch vụ không hỗ trợ: {service}")
    return int(round(p / 10_000.0) * 10_000)


def quote_total(services: list[str], pages: int) -> int:
    return sum(price_vnd(s, pages) for s in services)


def estimate_pages(path: Path) -> int:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext in (".docx", ".pptx", ".odt"):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "docProps/app.xml" in names:
                    m = re.search(rb"<Pages>(\d+)</Pages>", z.read("docProps/app.xml"))
                    if m and int(m.group(1)) > 0:
                        return int(m.group(1))
                if "word/document.xml" in names:
                    xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
                    words = len(" ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)).split())
                    return max(1, round(words / 350))
                slides = [n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)]
                if slides:
                    return max(1, len(slides))
        if ext == ".pdf":
            data = path.read_bytes()
            n = len(re.findall(rb"/Type\s*/Page(?!s)", data))
            return max(1, n)
        if ext in (".txt", ".md", ".rtf"):
            words = len(path.read_text(encoding="utf-8", errors="ignore").split())
            return max(1, round(words / 350))
    except (zipfile.BadZipFile, OSError):
        pass
    return 1


@dataclass
class Order:
    id: str
    code: str
    customer_email: str
    customer_name: str
    services: list[str]
    pages: int
    price_vnd: int
    status: str
    created_at: float
    updated_at: float
    quote_expires_at: float
    paid_vnd: int = 0
    paid_at: float = 0.0
    delivered_at: float = 0.0
    attempts: int = 0
    revisions_used: int = 0
    revision_notes: str = ""
    customer_notes: str = ""
    citation_style: str = ""
    inputs: list[str] = None  # type: ignore[assignment]
    outputs: list[str] = None  # type: ignore[assignment]
    thread_ids: list[str] = None  # type: ignore[assignment]
    history: list[list[Any]] = None  # type: ignore[assignment]
    qa: dict = None  # type: ignore[assignment]
    cost_usd: str = "0"
    escalation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Order":
        o = cls(**{k: d.get(k) for k in cls.__dataclass_fields__})
        for k in ("inputs", "outputs", "thread_ids", "history"):
            if getattr(o, k) is None:
                setattr(o, k, [])
        if o.qa is None:
            o.qa = {}
        return o


# Trạng thái: quoted -> paid -> processing -> delivered -> (revision -> delivered) -> closed
#             quoted -> expired ; bất kỳ -> failed/escalated -> refunded
OPEN_STATES = {"quoted", "paid", "processing", "revision", "delivering"}


class OrderStore:
    def __init__(self, state: StateDir, clock=time.time, prefix: str = "HT"):
        self.state = state
        self.clock = clock
        self.prefix = prefix
        self.path = state.root / "orders.json"

    def _load(self) -> dict[str, Any]:
        data = self.state.read_json(self.path, None) or {}
        data.setdefault("orders", {})
        data.setdefault("seen_tx", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.state.write_json(self.path, data)

    def all(self) -> list[Order]:
        return [Order.from_dict(d) for d in self._load()["orders"].values()]

    def get(self, code: str) -> Optional[Order]:
        d = self._load()["orders"].get(code)
        return Order.from_dict(d) if d else None

    def by_status(self, *statuses: str) -> list[Order]:
        return sorted([o for o in self.all() if o.status in statuses], key=lambda o: o.created_at)

    def find_by_thread(self, message_ids: list[str]) -> Optional[Order]:
        ids = {m for m in message_ids if m}
        for o in self.all():
            if ids & set(o.thread_ids or []):
                return o
        return None

    def new_code(self) -> str:
        existing = set(self._load()["orders"].keys())
        while True:
            code = self.prefix + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if code not in existing:
                return code

    def create(self, customer_email: str, customer_name: str, services: list[str], pages: int, inputs: list[str],
               quote_valid_days: int, notes: str = "", citation_style: str = "") -> Order:
        now = float(self.clock())
        code = self.new_code()
        o = Order(id=code, code=code, customer_email=customer_email, customer_name=customer_name,
                  services=services, pages=pages, price_vnd=quote_total(services, pages), status="quoted",
                  created_at=now, updated_at=now, quote_expires_at=now + quote_valid_days * 86400,
                  inputs=inputs, outputs=[], thread_ids=[], history=[[now, "created"]], qa={},
                  customer_notes=notes[:2000], citation_style=citation_style)
        self.save(o)
        return o

    def save(self, order: Order) -> None:
        with file_lock(self.state.lock_path):
            data = self._load()
            order.updated_at = float(self.clock())
            data["orders"][order.code] = order.to_dict()
            self._save(data)

    def event(self, order: Order, text: str, status: Optional[str] = None) -> Order:
        if status:
            order.status = status
        order.history.append([float(self.clock()), text])
        self.save(order)
        return order

    def tx_seen(self, tx_id: str) -> bool:
        return tx_id in set(self._load()["seen_tx"])

    def mark_tx(self, tx_id: str) -> None:
        with file_lock(self.state.lock_path):
            data = self._load()
            seen = data["seen_tx"]
            if tx_id not in seen:
                seen.append(tx_id)
                data["seen_tx"] = seen[-5000:]
            self._save(data)
