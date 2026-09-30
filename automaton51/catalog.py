"""Catalog: sản phẩm (web/app/công cụ số), việc (gig) tìm được, nội dung đã đăng."""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Optional

from .money import D, ZERO
from .state import StateDir, file_lock


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len] or "san-pham").strip("-")


class Catalog:
    def __init__(self, state: StateDir, clock=None):
        self.state = state
        self.clock = clock or time.time
        self._data: dict[str, Any] = {"products": {}, "jobs": {}, "posts": [], "counter": 0}
        self.load()

    # ---- lưu / nạp ----
    def load(self) -> None:
        data = self.state.read_json(self.state.catalog_path, None)
        if isinstance(data, dict):
            for k in ("products", "jobs"):
                data.setdefault(k, {})
            data.setdefault("posts", [])
            data.setdefault("counter", 0)
            self._data = data

    def save(self) -> None:
        with file_lock(self.state.lock_path):
            self.state.write_json(self.state.catalog_path, self._data)

    def _next_id(self, prefix: str) -> str:
        self._data["counter"] = int(self._data.get("counter", 0)) + 1
        return f"{prefix}{self._data['counter']:04d}"

    # ---- sản phẩm ----
    @property
    def products(self) -> dict[str, dict[str, Any]]:
        return self._data["products"]

    def add_product(self, name: str, description: str, price, kind: str, files: list[str],
                    quality: float, job_id: Optional[str] = None) -> dict[str, Any]:
        pid = self._next_id("P")
        slug = slugify(name)
        existing = {p["slug"] for p in self.products.values()}
        if slug in existing:
            slug = f"{slug}-{pid.lower()}"
        product = {
            "id": pid, "slug": slug, "name": name.strip()[:120], "description": description.strip()[:2000],
            "kind": kind, "price": f"{D(price):f}", "status": "draft", "files": files,
            "quality": round(float(quality), 3), "visibility": 0.0, "sales": 0, "revenue": "0",
            "created_at": float(self.clock()), "listed_at": None, "channels": [], "job_id": job_id,
            "buy_url": "",
        }
        self.products[pid] = product
        self.save()
        return product

    def get_product(self, pid: str) -> Optional[dict[str, Any]]:
        return self.products.get(pid)

    def list_products(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        items = list(self.products.values())
        if status:
            items = [p for p in items if p["status"] == status]
        return sorted(items, key=lambda p: p["created_at"])

    def update_product(self, pid: str, **changes) -> dict[str, Any]:
        p = self.products[pid]
        p.update(changes)
        self.save()
        return p

    def record_sale(self, pid: str, amount) -> None:
        p = self.products[pid]
        p["sales"] = int(p.get("sales", 0)) + 1
        p["revenue"] = f"{(D(p.get('revenue', '0')) + D(amount)):f}"
        self.save()

    # ---- việc ----
    @property
    def jobs(self) -> dict[str, dict[str, Any]]:
        return self._data["jobs"]

    def add_job(self, title: str, budget, description: str, source: str, url: str = "") -> dict[str, Any]:
        jid = self._next_id("J")
        job = {"id": jid, "title": title.strip()[:160], "budget": f"{D(budget):f}", "description": description.strip()[:2000],
               "source": source, "url": url, "status": "open", "found_at": float(self.clock()),
               "product_id": None, "submitted_at": None, "resolved_at": None, "outcome": None}
        self.jobs[jid] = job
        self.save()
        return job

    def get_job(self, jid: str) -> Optional[dict[str, Any]]:
        return self.jobs.get(jid)

    def list_jobs(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        items = list(self.jobs.values())
        if status:
            items = [j for j in items if j["status"] == status]
        return sorted(items, key=lambda j: j["found_at"])

    def update_job(self, jid: str, **changes) -> dict[str, Any]:
        j = self.jobs[jid]
        j.update(changes)
        self.save()
        return j

    # ---- nội dung ----
    @property
    def posts(self) -> list[dict[str, Any]]:
        return self._data["posts"]

    def add_post(self, platform: str, topic: str, text: str, product_id: Optional[str], path: str) -> dict[str, Any]:
        post = {"id": self._next_id("C"), "platform": platform, "topic": topic[:200], "text": text[:4000],
                "product_id": product_id, "path": path, "created_at": float(self.clock())}
        self.posts.append(post)
        if product_id and product_id in self.products:
            p = self.products[product_id]
            p["visibility"] = round(min(3.0, float(p.get("visibility", 0.0)) + 0.35), 3)
        self.save()
        return post

    # ---- tóm tắt cho prompt ----
    def summary(self, max_items: int = 8) -> str:
        lines: list[str] = []
        prods = self.list_products()
        lines.append(f"Sản phẩm: {len(prods)} (đang bán: {len([p for p in prods if p['status']=='listed'])})")
        for p in prods[-max_items:]:
            lines.append(f"  - {p['id']} [{p['status']}] {p['name']} | giá ${D(p['price']):.2f} | bán {p['sales']} | DT ${D(p['revenue']):.2f} | chất lượng {p['quality']} | hiển thị {p['visibility']}")
        jobs = self.list_jobs()
        open_jobs = [j for j in jobs if j["status"] in ("open", "submitted")]
        lines.append(f"Việc: {len(jobs)} tìm được, {len(open_jobs)} đang mở/đã nộp")
        for j in open_jobs[-max_items:]:
            lines.append(f"  - {j['id']} [{j['status']}] {j['title']} | ngân sách ${D(j['budget']):.2f} | nguồn {j['source']}")
        lines.append(f"Nội dung đã đăng: {len(self.posts)}")
        return "\n".join(lines)

    def totals(self) -> dict[str, Any]:
        prods = self.list_products()
        return {
            "products": len(prods),
            "listed": len([p for p in prods if p["status"] == "listed"]),
            "sales": sum(int(p.get("sales", 0)) for p in prods),
            "jobs_open": len(self.list_jobs("open")),
            "jobs_submitted": len(self.list_jobs("submitted")),
            "jobs_paid": len(self.list_jobs("paid")),
            "posts": len(self.posts),
        }
