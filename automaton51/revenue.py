"""Doanh thu.

Hai nguồn "thật" (chế độ live):
  * RevenueInbox: sự kiện doanh thu do chủ sở hữu ghi (`automaton51 revenue add`) hoặc
    do webhook thanh toán (Stripe/PayPal/SePay/Casso...) gửi vào dashboard.
Một nguồn mô phỏng (chế độ sim):
  * SimulatedMarket: thị trường giả lập có hạt giống, để chạy thử toàn bộ nền kinh tế
    mà không tốn một xu.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Optional

from .catalog import Catalog
from .money import D, ZERO
from .state import StateDir


@dataclass
class RevenueEvent:
    id: str
    ts: float
    amount: str
    currency: str
    source: str
    memo: str
    external_id: str = ""
    product_id: str = ""
    job_id: str = ""
    meta: dict[str, Any] | None = None

    @property
    def amount_d(self) -> Decimal:
        return D(self.amount)


class RevenueInbox:
    """Hộp thư doanh thu dạng JSONL; vòng lặp tiêu thụ theo con trỏ lưu trong kv."""

    def __init__(self, state: StateDir, clock=None):
        self.state = state
        self.clock = clock or time.time

    def append(self, amount, source: str, memo: str = "", currency: str = "USD", external_id: str = "",
               product_id: str = "", job_id: str = "", meta: dict | None = None) -> Optional[RevenueEvent]:
        amount = D(amount)
        if amount <= ZERO:
            raise ValueError("Doanh thu phải > 0")
        if external_id and any(e.get("external_id") == external_id for e in self.all()):
            return None  # trùng (webhook gửi lại)
        ev = RevenueEvent(id=uuid.uuid4().hex[:12], ts=float(self.clock()), amount=f"{amount:f}", currency=currency,
                          source=source, memo=memo, external_id=external_id, product_id=product_id,
                          job_id=job_id, meta=meta or {})
        self.state.append_jsonl(self.state.revenue_inbox_path, asdict(ev))
        return ev

    def all(self) -> list[dict[str, Any]]:
        return self.state.read_jsonl(self.state.revenue_inbox_path)

    def pending(self) -> list[RevenueEvent]:
        cursor = int(self.state.kv_get("revenue_cursor", 0) or 0)
        rows = self.all()
        out: list[RevenueEvent] = []
        for row in rows[cursor:]:
            try:
                out.append(RevenueEvent(**{k: row.get(k) for k in RevenueEvent.__dataclass_fields__}))
            except TypeError:
                continue
        return out

    def advance(self, count: int) -> None:
        cursor = int(self.state.kv_get("revenue_cursor", 0) or 0)
        self.state.kv_set("revenue_cursor", cursor + count)


class SimulatedMarket:
    """Thị trường giả lập, xác định bằng hạt giống (seed) để test lặp lại được."""

    JOB_TEMPLATES = [
        ("Landing page cho quán cà phê", 45, "Cần một trang giới thiệu 1 trang, có menu và bản đồ."),
        ("Bot Telegram nhắc lịch học", 60, "Bot nhắc lịch, cho phép thêm/xoá lịch, tiếng Việt."),
        ("Script gộp file Excel bán hàng", 25, "Gộp nhiều file xlsx thành một báo cáo tuần."),
        ("Tối ưu SEO cho blog du lịch", 40, "Viết lại 5 bài chuẩn SEO, gợi ý từ khoá."),
        ("Ứng dụng tính lãi vay", 35, "Web nhỏ tính lãi vay ngân hàng, xuất bảng trả nợ."),
        ("Chatbot FAQ cho cửa hàng", 80, "Bot trả lời câu hỏi thường gặp từ file FAQ."),
        ("Dịch và biên tập tài liệu kỹ thuật", 30, "Dịch 10 trang Anh-Việt, chuẩn thuật ngữ."),
        ("Dashboard theo dõi chi tiêu", 70, "Dashboard nhập chi tiêu, biểu đồ theo tháng."),
        ("Mẫu email chăm sóc khách hàng", 20, "Bộ 7 email tự động cho shop online."),
        ("Công cụ đặt lịch cho tiệm tóc", 55, "Đặt lịch online, nhắc SMS/Zalo."),
    ]
    SEARCH_RESULTS = [
        ("Việc freelance lập trình web nhỏ", "https://example.com/jobs/web"),
        ("Nhu cầu chatbot cho cửa hàng nhỏ tăng mạnh", "https://example.com/news/chatbot"),
        ("Người dùng tìm công cụ Excel tự động", "https://example.com/forum/excel"),
        ("Xu hướng nội dung ngắn thu hút khách", "https://example.com/blog/content"),
    ]

    def __init__(self, seed: int = 42, clock=None):
        self.rng = random.Random(seed)
        self.clock = clock or time.time

    # ---- công cụ cho tác nhân ----
    def search_web(self, query: str) -> list[dict[str, str]]:
        k = self.rng.randint(2, 4)
        return [{"title": t, "url": u, "snippet": f"Kết quả mô phỏng cho '{query[:40]}'"}
                for t, u in self.rng.sample(self.SEARCH_RESULTS, k)]

    def fetch_url(self, url: str) -> str:
        return f"[MÔ PHỎNG] Nội dung trang {url}: khách hàng nhỏ cần web/app/công cụ rẻ, giao nhanh, hỗ trợ tiếng Việt."

    # Xác suất tìm được việc mỗi lần tìm: 50% không có, 35% một việc, 15% hai việc (thị trường cạnh tranh)
    JOB_FIND_WEIGHTS = ([0] * 65) + ([1] * 28) + ([2] * 7)
    JOB_ACCEPT_PROB = 0.12          # tân binh không danh tiếng thắng thầu ~1/8
    JOB_EXPIRY_DAYS = 3.0           # việc mở quá 3 ngày không nộp -> hết hạn
    STORE_DAILY_BASE = 0.03         # xác suất bán mỗi ngày cho sản phẩm chất lượng 1.0, hiển thị 0

    def find_jobs(self, keywords: str, catalog: Catalog) -> list[dict[str, Any]]:
        n = self.rng.choice(self.JOB_FIND_WEIGHTS)
        found: list[dict[str, Any]] = []
        for title, budget, desc in self.rng.sample(self.JOB_TEMPLATES, n):
            budget_var = D(budget) * D(self.rng.uniform(0.5, 1.1))
            found.append(catalog.add_job(title, D(budget_var).quantize(D("0.01")), desc, source="sim-market",
                                         url=f"https://example.com/jobs/{uuid.uuid4().hex[:6]}"))
        return found

    # ---- diễn biến mỗi tick ----
    def step(self, catalog: Catalog, tick_hours: float, now: float) -> list[dict[str, Any]]:
        """Trả về danh sách doanh thu phát sinh trong tick này."""
        events: list[dict[str, Any]] = []
        tick_days = tick_hours / 24.0
        # 0) việc mở quá lâu -> hết hạn
        for job in catalog.list_jobs("open"):
            if (now - float(job["found_at"])) / 86400.0 > self.JOB_EXPIRY_DAYS:
                catalog.update_job(job["id"], status="expired", resolved_at=now, outcome="expired")
        # 1) việc đã nộp -> khách quyết định sau 1..3 ngày; nhận với xác suất JOB_ACCEPT_PROB
        for job in catalog.list_jobs("submitted"):
            waited_days = (now - float(job["submitted_at"] or now)) / 86400.0
            if waited_days < 1.0:
                continue
            decide_prob = 0.5 * tick_days * 24 / 24 + (1.0 if waited_days >= 3.0 else 0.0)
            if self.rng.random() < decide_prob:
                if self.rng.random() < self.JOB_ACCEPT_PROB:
                    amount = D(job["budget"])
                    catalog.update_job(job["id"], status="paid", resolved_at=now, outcome="accepted")
                    events.append({"amount": amount, "source": "job", "job_id": job["id"], "product_id": job.get("product_id") or "",
                                   "memo": f"Khách thanh toán việc {job['id']}: {job['title']}"})
                else:
                    catalog.update_job(job["id"], status="rejected", resolved_at=now, outcome="rejected")
        # 2) sản phẩm đang bán -> có người mua với xác suất theo chất lượng, hiển thị, bão hoà
        for p in catalog.list_products("listed"):
            quality = float(p.get("quality", 0.5))
            visibility = float(p.get("visibility", 0.0))
            saturation = 1.0 / (1.0 + int(p.get("sales", 0)) / 3.0)
            daily_rate = self.STORE_DAILY_BASE * quality * (0.4 + visibility) * saturation
            prob = min(0.5, daily_rate * tick_days)
            if self.rng.random() < prob:
                amount = D(p["price"])
                catalog.record_sale(p["id"], amount)
                events.append({"amount": amount, "source": "store", "product_id": p["id"], "job_id": "",
                               "memo": f"Bán {p['name']} ({p['id']})"})
            # hiển thị giảm dần (nội dung cũ đi): mất ~10%/ngày
            catalog.update_product(p["id"], visibility=round(visibility * (1.0 - 0.10 * tick_days), 3))
        return events
