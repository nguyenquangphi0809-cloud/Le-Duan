"""Bộ não mô phỏng: chính sách heuristic có hạt giống, KHÔNG gọi API, nhưng vẫn
'tiêu token' giả để nền kinh tế (chi phí suy luận, tầng sinh tồn, chia 51/49) chạy thật.
Dùng để chạy thử, viết test và xem dashboard trước khi bật chế độ live."""
from __future__ import annotations

import random
import re
from typing import Any, Optional

from .base import Brain, BrainStep, ToolCall

PRODUCT_IDEAS = [
    ("Landing page quán cà phê", "web", 39, "Trang giới thiệu 1 trang, có menu, bản đồ, nút gọi/Zalo; responsive."),
    ("Bộ mẫu email chăm sóc khách", "template", 19, "7 email tự động cho shop online: chào mừng, nhắc giỏ hàng, hậu mãi."),
    ("Script gộp Excel bán hàng", "script", 24, "Gộp nhiều file xlsx thành báo cáo tuần, có biểu đồ."),
    ("Bot Telegram nhắc lịch", "app", 49, "Bot nhắc lịch cá nhân, thêm/xoá lịch bằng tiếng Việt."),
    ("Công cụ tính lãi vay", "web", 29, "Web tính lãi vay ngân hàng, xuất bảng trả nợ."),
    ("Chatbot FAQ cửa hàng", "app", 69, "Bot trả lời câu hỏi thường gặp từ file FAQ."),
]


class SimulatedBrain(Brain):
    name = "simulated"

    def __init__(self, seed: int = 42, max_steps: int = 5):
        self.rng = random.Random(seed)
        self.max_steps = max_steps
        self.model = "claude-opus-5-5"
        self.effort = "high"
        self._ctx: dict[str, Any] = {}
        self._step = 0
        self._done: set[str] = set()
        self._turn_no = 0
        self._is_building = False
        self._pending_job: Optional[dict[str, Any]] = None
        self._new_product = False

    def set_model(self, model: str, effort: str) -> None:
        self.model, self.effort = model, effort

    def begin_turn(self, system: str, turn_input: str, tools: list[dict[str, Any]], context: dict[str, Any]) -> None:
        self._ctx = dict(context)
        self._step = 0
        self._done = set()
        self._turn_no += 1
        self._pending_job = None
        self._new_product = False

    # ---- token giả: bước sau dài hơn bước trước (lịch sử dài ra), phần system được cache ----
    def _usage(self) -> dict[str, int]:
        first = self._step == 1
        return {
            "input_tokens": 900 + 500 * self._step + self.rng.randint(0, 300),
            "output_tokens": (900 if self._is_building else 260) + self.rng.randint(0, 120),
            "cache_creation_input_tokens": 2200 if first else 0,
            "cache_read_input_tokens": 0 if first else 2200,
        }

    def step(self, tool_results: Optional[list[dict[str, Any]]]) -> BrainStep:
        self._step += 1
        self._is_building = False
        if tool_results:
            for r in tool_results:
                if r.get("is_error"):
                    self._done.add("error")
                m = re.search(r"Đã tạo sản phẩm (P\d+)", str(r.get("content", "")))
                if m:
                    self._ctx["last_product_id"] = m.group(1)
        call = self._decide() if self._step <= self.max_steps else None
        if call is None:
            return BrainStep(text=self._journal(), tool_calls=[], usage=self._usage(), model=self.model, stop_reason="end_turn")
        return BrainStep(text="", tool_calls=[call], usage=self._usage(), model=self.model, stop_reason="tool_use")

    def _call(self, tool_name: str, **kwargs) -> ToolCall:
        self._done.add(tool_name)
        return ToolCall(id=f"sim_{self._turn_no}_{self._step}", name=tool_name, input=kwargs)

    def _decide(self) -> Optional[ToolCall]:
        c = self._ctx
        tier = c.get("tier", "normal")
        listed = c.get("listed", 0)
        open_jobs: list[dict[str, Any]] = c.get("open_jobs", [])
        posts = c.get("posts", 0)
        products_total = c.get("products", 0)
        low_money = tier in ("low_compute", "critical")

        if tier == "critical" and "request_funding" not in self._done and c.get("can_request_funding", True) and self._step == 1:
            return self._call("request_funding", amount_usd=10, reason="Ví vận hành cạn, cần vốn để tiếp tục tạo doanh thu")
        # 1) có việc mở -> làm sản phẩm rồi nộp (thu tiền nhanh nhất)
        if open_jobs and "write_product" not in self._done:
            job = max(open_jobs, key=lambda j: float(j["budget"]))
            self._is_building = True
            self._pending_job = job
            return self._call("write_product", name=f"Giao hàng: {job['title']}", kind="web",
                              description=f"Sản phẩm hoàn chỉnh cho việc {job['id']}: {job['description']}",
                              price_usd=float(job["budget"]), job_id=job["id"],
                              files=self._fake_files(job["title"]))
        if "write_product" in self._done and getattr(self, "_pending_job", None) and "submit_work" not in self._done:
            job = self._pending_job
            pid = c.get("last_product_id") or self._guess_last_product_id()
            self._pending_job = None
            return self._call("submit_work", job_id=job["id"], product_id=pid, message="Đã hoàn thành theo mô tả, kèm hướng dẫn cài đặt.")
        # 2) ít sản phẩm đang bán -> tìm việc hoặc làm sản phẩm mới
        if not low_money and "find_jobs" not in self._done and self.rng.random() < 0.6:
            return self._call("find_jobs", keywords="web app script freelance việt nam")
        if listed < 3 and "write_product" not in self._done and (not low_money or listed == 0):
            name, kind, price, desc = self.rng.choice(PRODUCT_IDEAS)
            self._is_building = True
            self._new_product = True
            return self._call("write_product", name=name, kind=kind, description=desc, price_usd=price, job_id="",
                              files=self._fake_files(name))
        if getattr(self, "_new_product", False) and "publish_listing" not in self._done:
            self._new_product = False
            pid = c.get("last_product_id") or self._guess_last_product_id()
            return self._call("publish_listing", product_id=pid, price_usd=float(self.rng.choice([19, 24, 29, 39, 49])), channels=["storefront", "facebook"])
        # 3) nội dung để tăng hiển thị (mỗi lượt tối đa 1)
        listed_ids: list[str] = c.get("listed_ids", [])
        if listed_ids and "create_content" not in self._done and posts < 40 and (not low_money or self.rng.random() < 0.3):
            pid = self.rng.choice(listed_ids)
            return self._call("create_content", platform=self.rng.choice(["tiktok", "facebook", "blog"]),
                              topic=f"3 lỗi khiến bạn mất khách và cách {pid} khắc phục",
                              text="Nhiều cửa hàng nhỏ mất khách vì phản hồi chậm, không có trang giới thiệu và không nhắc lịch. "
                                   "Bài này chia sẻ cách khắc phục từng lỗi với công cụ đơn giản, kèm ví dụ thực tế và checklist.",
                              product_id=pid)
        if "check_sales" not in self._done and self._step >= 2:
            return self._call("check_sales")
        if "sleep" not in self._done and self._step >= 2:
            idle = listed >= 2 and not open_jobs
            secs = 4 * 3600 if (idle or low_money) else 2 * 3600
            return self._call("sleep", seconds=secs, reason="Chờ khách hàng; tiết kiệm chi phí suy luận")
        return None

    def _guess_last_product_id(self) -> str:
        return self._ctx.get("last_product_id") or "P0001"

    def _fake_files(self, title: str) -> list[dict[str, str]]:
        body = "\n".join(f"// dòng {i}: xử lý {title}" for i in range(1, 60))
        return [
            {"path": "README.md", "content": f"# {title}\n\nHướng dẫn cài đặt và sử dụng.\n" + "Chi tiết. " * 80},
            {"path": "index.html", "content": f"<!doctype html><html><head><title>{title}</title></head><body><h1>{title}</h1></body></html>" + "<!-- -->" * 100},
            {"path": "app.js", "content": body},
        ]

    def _journal(self) -> str:
        c = self._ctx
        return (f"Nhật ký (mô phỏng): tầng {c.get('tier')}, ví vận hành ${c.get('operating', '?')}, "
                f"{c.get('listed', 0)} sản phẩm đang bán, {len(c.get('open_jobs', []))} việc mở. "
                f"Hành động lượt này: {', '.join(sorted(self._done - {'error'})) or 'không'}.")
