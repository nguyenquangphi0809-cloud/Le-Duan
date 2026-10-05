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

# Hai ngách chạy song song trên cùng một hệ thống:
#   A — hồ sơ bảo vệ luận án (nghiên cứu sinh, học viên cao học)
#   B — số hoá và biên soạn sử liệu địa phương (người biên soạn lịch sử Đảng bộ, lịch sử truyền thống xã/phường)
# accepts: đuôi tệp xử lý được; max_pages: giới hạn mỗi đơn (đơn lớn hơn -> báo giá dự án riêng).
DOC = (".docx",)
DOC_PDF = (".docx", ".pdf")
SCAN = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
SERVICES: dict[str, dict[str, Any]] = {
    "DF": {"name": "Định dạng theo mẫu trường / Thông tư", "hours": 24, "line": "A", "accepts": DOC},
    "TK": {"name": "Chuẩn hoá tài liệu tham khảo và đối chiếu trích dẫn", "hours": 24, "line": "A", "accepts": DOC},
    "HD": {"name": "Hiệu đính ngôn ngữ học thuật (Track Changes)", "hours": 72, "line": "A", "accepts": DOC},
    "AB": {"name": "Tóm tắt tiếng Anh, từ khoá, thư gửi tạp chí", "hours": 24, "line": "A", "accepts": DOC_PDF},
    "TT": {"name": "Biên tập quyển tóm tắt luận án từ toàn văn (có đối chiếu trang)", "hours": 72, "line": "A", "accepts": DOC_PDF},
    "TA": {"name": "Bản tiếng Anh của quyển tóm tắt luận án", "hours": 48, "line": "A", "accepts": DOC_PDF},
    "DG": {"name": "Trang thông tin đóng góp mới của luận án (Việt – Anh)", "hours": 24, "line": "A", "accepts": DOC_PDF},
    "PB": {"name": "Bộ câu hỏi luyện phản biện và slide bảo vệ", "hours": 72, "line": "A", "accepts": DOC_PDF},
    "CP": {"name": "Chuyển phông TCVN3/VNI sang Unicode", "hours": 1, "line": "B", "accepts": (".docx", ".txt")},
    "SH": {"name": "Số hoá bản scan/ảnh chụp: nhận dạng chữ, xuất Word Unicode", "hours": 72, "line": "B", "accepts": SCAN,
           "max_pages": 60},
    "NB": {"name": "Biên niên sự kiện hợp nhất và bảng đối chiếu chỗ các nguồn ghi khác nhau", "hours": 120, "line": "B",
           "accepts": (".docx", ".pdf", ".txt")},
    "BT": {"name": "Biên tập kỹ thuật bản thảo lịch sử địa phương và bảng tra cứu nhân danh, địa danh", "hours": 120,
           "line": "B", "accepts": DOC},
}
# Gói: đặt đủ các dịch vụ trong gói thì tự giảm giá
BUNDLES: dict[str, dict[str, Any]] = {
    "BV": {"name": "Gói sẵn sàng bảo vệ luận án tiến sĩ", "items": ["DF", "TK", "TT", "TA", "DG", "PB"], "discount": 0.15,
           "line": "A"},
    "LV": {"name": "Gói nộp luận văn thạc sĩ", "items": ["DF", "TK", "AB"], "discount": 0.10, "line": "A"},
    "XM": {"name": "Gói hợp nhất sử liệu xã mới (số hoá + biên niên)", "items": ["SH", "NB"], "discount": 0.10, "line": "B"},
}
LINES = {"A": "Hồ sơ bảo vệ luận án", "B": "Số hoá và biên soạn sử liệu địa phương"}
CP_FREE_PAGES = 50
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ 0/O, 1/I dễ nhầm


def _round(p: float) -> int:
    return int(round(p / 10_000.0) * 10_000)


def price_vnd(service: str, pages: int) -> int:
    pages = max(1, int(pages))
    if service == "DF":
        p = min(900_000, 400_000 + 5_000 * max(0, pages - 60))
    elif service == "TK":
        p = min(800_000, 300_000 + 4_000 * max(0, pages - 60))
    elif service == "HD":
        p = max(400_000, 12_000 * pages)
    elif service == "AB":
        p = 300_000
    elif service == "PB":
        p = min(1_500_000, 900_000 + 3_000 * max(0, pages - 80))
    elif service == "TT":
        p = min(2_000_000, 1_500_000 + 5_000 * max(0, pages - 150))
    elif service == "TA":
        p = 1_500_000
    elif service == "DG":
        p = 400_000
    elif service == "CP":
        return 0 if pages <= CP_FREE_PAGES else max(50_000, _round(1_000 * pages))
    elif service == "SH":
        p = max(300_000, 6_000 * pages)
    elif service == "NB":
        p = max(2_000_000, 15_000 * pages)
    elif service == "BT":
        p = max(3_000_000, 30_000 * pages)
    else:
        raise ValueError(f"Dịch vụ không hỗ trợ: {service}")
    return _round(p)


PRICE_TEXT = {
    "DF": "400.000–900.000 đ (theo số trang)",
    "TK": "300.000–800.000 đ (theo số trang)",
    "HD": "12.000 đ/trang, tối thiểu 400.000 đ",
    "AB": "300.000 đ",
    "PB": "900.000–1.500.000 đ (theo số trang)",
    "TT": "1.500.000–2.000.000 đ (theo số trang)",
    "TA": "1.500.000 đ",
    "DG": "400.000 đ",
    "CP": f"miễn phí tới {CP_FREE_PAGES} trang; trên {CP_FREE_PAGES} trang 1.000 đ/trang",
    "SH": "6.000 đ/trang, tối thiểu 300.000 đ (tối đa 60 trang mỗi lần gửi)",
    "NB": "15.000 đ/trang tài liệu nguồn, tối thiểu 2.000.000 đ",
    "BT": "30.000 đ/trang, tối thiểu 3.000.000 đ",
}
BUNDLE_TEXT = {
    "BV": "giảm 15% khi đặt đủ 6 dịch vụ: định dạng, tài liệu tham khảo, quyển tóm tắt, bản tiếng Anh của tóm tắt, "
          "trang đóng góp mới, luyện phản biện (luận án 180 trang ≈ 5.470.000 đ thay vì 6.430.000 đ)",
    "LV": "giảm 10% cho định dạng + tài liệu tham khảo + tóm tắt tiếng Anh (luận văn 100 trang ≈ 1.220.000 đ)",
    "XM": "giảm 10% cho số hoá + biên niên hợp nhất cùng một bộ tài liệu",
}


def hours_text(hours: int) -> str:
    return f"{hours} giờ" if hours < 48 else f"{hours // 24} ngày"


def expand_services(codes: list[str]) -> list[str]:
    """Thay mã gói (BV, LV, XM) bằng các dịch vụ trong gói, bỏ trùng, xếp theo thứ tự của bảng dịch vụ."""
    wanted: set[str] = set()
    for c in codes:
        wanted.update(BUNDLES[c]["items"] if c in BUNDLES else [c])
    return [s for s in SERVICES if s in wanted]


def bundles_in(services: list[str]) -> list[str]:
    """Các gói được giảm giá; mỗi dịch vụ chỉ được giảm trong một gói (gói lớn xét trước)."""
    used: set[str] = set()
    out: list[str] = []
    for b, spec in sorted(BUNDLES.items(), key=lambda kv: -len(kv[1]["items"])):
        if all(s in services and s not in used for s in spec["items"]):
            out.append(b)
            used |= set(spec["items"])
    return out


def quote_total(services: list[str], pages: int) -> int:
    services = expand_services(services)
    total = sum(price_vnd(s, pages) for s in services)
    for b in bundles_in(services):
        spec = BUNDLES[b]
        total -= _round(sum(price_vnd(s, pages) for s in spec["items"]) * spec["discount"])
    return max(0, total)


def line_of(services: list[str]) -> str:
    """Ngách của đơn: B nếu có dịch vụ ngách B, ngược lại A."""
    return "B" if any(SERVICES.get(s, {}).get("line") == "B" for s in services) else "A"


def max_pages_for(services: list[str], default: int) -> int:
    return min([default] + [int(SERVICES[s]["max_pages"]) for s in services if s in SERVICES and SERVICES[s].get("max_pages")])


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
