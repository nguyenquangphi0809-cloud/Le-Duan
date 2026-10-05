"""Bộ điều phối vận hành tự động. Mỗi lần chạy (mặc định 2 phút một lần, trong nhịp tim):

  1. dò tiền về -> khớp mã đơn -> ghi doanh thu (VND -> USD) -> báo khách
  2. đọc thư mới gửi tới địa chỉ kinh doanh -> trả lời / báo giá / từ chối / nhận yêu cầu sửa
  3. xử lý đơn đã thanh toán bằng Claude -> kiểm tra chất lượng tự động -> giao hàng
  4. hết hạn báo giá, đóng đơn quá hạn sửa
  5. gửi thư xin phép cho danh bạ (tối đa N thư/ngày, 8–20 giờ giờ Việt Nam), chia theo hai ngách
  6. đăng bài lên Trang Facebook (nếu có token), chia theo hai ngách
  7. chạy quảng cáo trả tiền trích từ Quỹ mở rộng 49% (nếu bật, mặc định tắt)
  8. gửi báo cáo hằng ngày cho chủ sở hữu (kèm lãi lỗ từng ngách)
  9. xoá dữ liệu khách quá hạn lưu trữ

Hai ngách chạy song song trên cùng hệ thống: A — hồ sơ bảo vệ luận án; B — số hoá, biên soạn sử liệu địa phương.
Bài đăng và thư giới thiệu được chia theo lãi gộp 60 ngày của từng ngách (mỗi ngách giữ tối thiểu 25%).

Việc duy nhất cần người: chuyển tiền HOÀN lại cho khách khi đơn thất bại hoặc bị khiếu nại hết lượt sửa.
Hệ thống gửi sẵn hướng dẫn cụ thể (số tiền, mã đơn, lệnh ghi sổ).
"""
from __future__ import annotations

import re
import shutil
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from ..catalog import Catalog
from ..config import Config
from ..economics import inference_cost
from ..ledger import Ledger
from ..money import D, ZERO, fmt
from ..state import StateDir
from . import templates as T
from .ads import AdsError, MetaAds, post_engagement
from .docx_tools import QAResult, docx_text_from_bytes, qa_check
from .facebook import FacebookPublisher, launch_kit_posts, tagged_posts
from .fulfillment import FulfillmentError, FulfillmentResult, plan_groups
from .intake import COMPLAINT_WORDS, REVISION_WORDS, Intent, _has_any, classify, fold, is_classified, is_personnel
from .legacy_fonts import convert_docx, convert_plain, docx_legacy_report
from .mail import InboundEmail, MailClient, OutboundEmail, addressed_to, strip_quoted
from .orders import (CP_FREE_PAGES, LINES, SERVICES, Order, OrderStore, estimate_pages, expand_services, line_of,
                     max_pages_for, quote_total)
from .outreach import OutreachStore, given_name
from .payments import BankTransaction, PaymentSource, find_code, vietqr_url

MAX_ATTEMPTS = 3
INFRA_ALERT_EVERY_S = 12 * 3600  # nhắc chủ sở hữu về sự cố hạ tầng tối đa 2 lần/ngày

INFRA_ADVICE = {
    "billing": ("Hết tiền API Claude",
                "Tài khoản API Claude đã hết tiền nên AI tạm ngừng xử lý đơn (đơn KHÔNG bị huỷ, khách KHÔNG bị hoàn tiền).\n"
                "Việc cần làm: nạp thêm tại https://platform.claude.com/settings/billing (nên bật Auto reload để tự nạp).\n"
                "Nạp xong, AI tự làm tiếp ở nhịp sau. Nếu muốn ghi sổ khoản nạp: automaton51 fund <số USD>."),
    "auth": ("Khoá API Claude bị từ chối",
             "Khoá API Claude không còn hợp lệ (bị xoá, hết hạn hoặc sai) nên AI tạm ngừng xử lý đơn.\n"
             "Việc cần làm: tạo khoá mới tại https://platform.claude.com/settings/keys, rồi bấm đúp "
             "deploy\\lenh-nhanh-windows.bat, chọn 6 (đổi thông tin) và dán khoá mới."),
    "transient": ("Không kết nối được máy chủ Claude",
                  "Mất mạng hoặc máy chủ Claude đang quá tải/bảo trì. AI giữ nguyên đơn và tự thử lại mỗi vài phút.\n"
                  "Thường không cần làm gì; nếu kéo dài, kiểm tra Internet của máy đang chạy AI."),
}


def _sender_matches(customer_name: str, content: str) -> bool:
    """Tên khách (ít nhất 2 chữ) xuất hiện đầy đủ trong nội dung chuyển khoản (ngân hàng thường tự ghi tên người chuyển)."""
    name = [t for t in re.split(r"[^a-z0-9]+", fold(customer_name or "")) if t]
    words = set(re.split(r"[^a-z0-9]+", fold(content or "")))
    return len(name) >= 2 and all(t in words for t in name)


def infra_problem(exc: BaseException) -> Optional[str]:
    """Lỗi do hạ tầng (không phải do đơn hàng): 'billing' | 'auth' | 'transient' | None."""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    body = getattr(exc, "body", None)
    etype = ""
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        etype = str(err.get("type", "") or "").lower()
    if status == 402 or etype == "billing_error" or "credit balance" in text:
        return "billing"
    if status in (401, 403) or etype in ("authentication_error", "permission_error"):
        return "auth"
    if status in (408, 409, 429, 500, 502, 503, 504, 529) or etype in (
            "rate_limit_error", "overloaded_error", "api_error", "timeout_error"):
        return "transient"
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError") or isinstance(exc, (ConnectionError, TimeoutError)):
        return "transient"
    return None
PREAUTH_USD = D("3")
VN_OFFSET_HOURS = 7
REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST_PATH = REPO_ROOT / "playbooks" / "launch-kit" / "01-checklist-20-loi-trinh-bay.md"
FB_POSTS_PATH = REPO_ROOT / "playbooks" / "launch-kit" / "03-bai-dang-facebook-tuan-1.md"
LINE_POSTS_PATH = REPO_ROOT / "playbooks" / "launch-kit" / "08-bai-dang-hai-ngach.md"


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _vn_hour(ts: float) -> int:
    return (time.gmtime(ts).tm_hour + VN_OFFSET_HOURS) % 24


class InfraPause(Exception):
    """Dừng xử lý đơn vì sự cố hạ tầng (hết tiền API, sai khoá, mất mạng)."""


class Operations:
    def __init__(self, state: StateDir, cfg: Config, ledger: Ledger, catalog: Catalog, clock: Callable[[], float],
                 mail: Optional[MailClient] = None, payments: Optional[PaymentSource] = None, fulfiller: Any = None,
                 llm_classify: Optional[Callable[[str, str], dict]] = None, facebook: Optional[FacebookPublisher] = None,
                 log: Callable[[str], None] = print, checklist_text: Optional[str] = None,
                 fb_fallback_posts: Optional[list[str]] = None, line_posts: Optional[list[tuple[str, str]]] = None,
                 ads: Optional[MetaAds] = None):
        self.state, self.cfg, self.ledger, self.catalog, self.clock = state, cfg, ledger, catalog, clock
        self.mail, self.payments, self.fulfiller, self.llm_classify, self.facebook = mail, payments, fulfiller, llm_classify, facebook
        self.ads = ads
        self.log = log
        self._current: Optional[Order] = None  # đơn đang xử lý: để ghi chi phí AI đúng đơn, đúng ngách
        self.orders = OrderStore(state, clock, cfg.order_code_prefix)
        self.outreach = OutreachStore(state, clock)
        if checklist_text is None:
            try:
                checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8")
            except OSError:
                checklist_text = "Checklist đang được cập nhật."
        self.checklist_text = checklist_text
        self.fb_fallback_posts = fb_fallback_posts if fb_fallback_posts is not None else launch_kit_posts(FB_POSTS_PATH)
        self.line_posts = line_posts if line_posts is not None else tagged_posts(LINE_POSTS_PATH)
        self.orders_dir = state.workspace / "orders"

    # ------------------------------------------------------------------ tiện ích chung
    @property
    def owner(self) -> str:
        return self.cfg.owner_name

    def _kv_inc(self, key: str, n: int = 1) -> int:
        v = int(self.state.kv_get(key, 0) or 0) + n
        self.state.kv_set(key, v)
        return v

    def _count(self, name: str, n: int = 1) -> None:
        key = f"ops_count:{_day(self.clock())}"
        data = self.state.kv_get(key, {}) or {}
        data[name] = int(data.get(name, 0)) + n
        self.state.kv_set(key, data)

    def _error(self, text: str) -> None:
        self.log(f"✗ ops: {text}")
        errs = (self.state.kv_get("ops_errors", []) or [])[-19:]
        errs.append([self.clock(), text[:300]])
        self.state.kv_set("ops_errors", errs)

    def charge_usage(self, usage: dict, model: str, memo: str) -> Decimal:
        cost = inference_cost(model, usage)
        meta: dict[str, Any] = {"model": model, **{k: int(v) for k, v in usage.items()}}
        if self._current is not None:
            meta.update({"order": self._current.code, "line": line_of(self._current.services)})
        return self._charge_capped(cost, "inference", memo, meta)

    def charge_fn(self, memo: str) -> Callable[[dict, str], None]:
        return lambda usage, model: self.charge_usage(usage, model, memo) and None

    def _charge_capped(self, amount: Decimal, category: str, memo: str, meta: Optional[dict] = None) -> Decimal:
        amount = D(amount)
        if amount <= ZERO:
            return ZERO
        self.ledger.reload()
        bal = self.ledger.balance("operating")
        meta = dict(meta or {})
        if amount > bal:
            meta["overrun"] = f"{(amount - bal):f}"
            amount = bal
        if amount > ZERO:
            self.ledger.charge(amount, category, memo, meta)
        return amount

    def _send(self, to: str, subject: str, text: str, attachments: Optional[list[Path]] = None, in_reply_to: str = "",
              references: Optional[list[str]] = None, kind: str = "tx") -> Optional[str]:
        if not self.mail or not to:
            return None
        if kind == "marketing" and self.outreach.is_suppressed(to):
            return None
        key = f"ops_emails:{_day(self.clock())}"
        if kind != "owner" and int(self.state.kv_get(key, 0) or 0) >= self.cfg.max_emails_per_day:
            self._error(f"đã chạm giới hạn {self.cfg.max_emails_per_day} thư/ngày, hoãn thư tới {to}")
            return None
        try:
            mid = self.mail.send(OutboundEmail(to=to, subject=subject, text=text, attachments=list(attachments or []),
                                               in_reply_to=in_reply_to, references=list(references or [])))
        except Exception as exc:  # noqa: BLE001 - lỗi mạng/SMTP: báo lỗi, người gọi tự thử lại
            self._error(f"gửi thư tới {to} lỗi: {type(exc).__name__}: {exc}")
            return None
        self._kv_inc(key)
        return mid

    def _reply(self, em: InboundEmail, subject: str, text: str, attachments: Optional[list[Path]] = None,
               order: Optional[Order] = None) -> Optional[str]:
        mid = self._send(em.from_addr, subject, text, attachments, in_reply_to=em.message_id, references=em.references)
        if order is not None and mid:
            order.thread_ids += [x for x in (em.message_id, mid) if x and x not in order.thread_ids]
            self.orders.save(order)
        return mid

    def _order_dir(self, code: str) -> Path:
        d = self.orders_dir / code
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _bank_line(self) -> str:
        return f"{self.cfg.bank_id.upper()} · STK {self.cfg.bank_account_number} · {self.cfg.bank_account_name}"

    def sender_block(self) -> str:
        """Thông tin người gửi in trong thư quảng cáo (Nghị định 91/2020)."""
        parts = [f"Người gửi: {self.owner or self.cfg.business_name}", f"Email: {self.cfg.email_alias}"]
        if self.cfg.business_address:
            parts.append(f"Địa chỉ: {self.cfg.business_address}")
        if self.cfg.business_phone:
            parts.append(f"Điện thoại: {self.cfg.business_phone}")
        if self.cfg.business_website:
            parts.append(f"Trang: {self.cfg.business_website}")
        return " · ".join(parts)

    # ------------------------------------------------------------------ hai ngách: lãi gộp và tỷ trọng
    def line_stats(self, now: float, days: int = 60) -> dict[str, dict[str, Any]]:
        since = now - days * 86400
        self.ledger.reload()
        stats: dict[str, dict[str, Any]] = {ln: {"revenue_usd": ZERO, "cost_usd": ZERO, "quotes": 0, "paid": 0, "free": 0}
                                            for ln in LINES}
        for e in self.ledger.entries:
            ln = (e.meta or {}).get("line")
            if e.ts < since or ln not in stats:
                continue
            if e.kind == "revenue":
                stats[ln]["revenue_usd"] += e.amount
            elif e.kind == "cost":
                stats[ln]["cost_usd"] += -e.amount
        for o in self.orders.all():
            if o.created_at < since or o.status in ("declined", "proposal"):
                continue
            st = stats[line_of(o.services)]
            if o.price_vnd == 0:
                st["free"] += 1
            else:
                st["quotes"] += 1
            if o.paid_vnd > 0:
                st["paid"] += 1
        for st in stats.values():
            st["margin_usd"] = st["revenue_usd"] - st["cost_usd"]
        return stats

    def line_weights(self, now: float) -> dict[str, float]:
        """Tỷ trọng bài đăng/thư giới thiệu cho từng ngách theo lãi gộp 60 ngày, mỗi ngách tối thiểu line_min_share."""
        floor = min(0.5, max(0.0, float(D(self.cfg.line_min_share))))
        margins = {ln: max(0.0, float(st["margin_usd"])) for ln, st in self.line_stats(now).items()}
        total = sum(margins.values())
        if total <= 0:
            return {ln: 1.0 / len(LINES) for ln in LINES}
        raw = {ln: m / total for ln, m in margins.items()}
        low = {ln for ln, r in raw.items() if r < floor}
        rest = 1.0 - floor * len(low)
        high_total = sum(r for ln, r in raw.items() if ln not in low) or 1.0
        return {ln: (floor if ln in low else rest * raw[ln] / high_total) for ln in raw}

    def _pick_line(self, key: str, now: float, allowed: Optional[set[str]] = None) -> str:
        """Chia lượt theo tỷ trọng (round-robin có trọng số, lưu "điểm" trong kv để bền qua khởi động lại)."""
        weights = {ln: w for ln, w in self.line_weights(now).items() if allowed is None or ln in allowed}
        if not weights:
            return "A"
        credit = dict(self.state.kv_get(key, {}) or {})
        for ln, w in weights.items():
            credit[ln] = float(credit.get(ln, 0.0)) + w
        best = max(weights, key=lambda ln: (credit[ln], ln == "A"))
        credit[best] -= sum(weights.values())
        self.state.kv_set(key, credit)
        return best

    # ------------------------------------------------------------------ vòng chạy
    def step(self, force: bool = False) -> dict[str, Any]:
        now = float(self.clock())
        if not self.cfg.ops_enabled:
            return {"skipped": "ops_disabled"}
        last = float(self.state.kv_get("ops_last_run", 0) or 0)
        if not force and now - last < self.cfg.ops_poll_seconds:
            return {"skipped": "poll_interval"}
        self.state.kv_set("ops_last_run", now)
        report: dict[str, Any] = {}
        for name, fn in (("payments", self._payments), ("inbox", self._inbox), ("fulfill", self._fulfill),
                         ("lifecycle", self._lifecycle), ("outreach", self._outreach), ("facebook", self._facebook),
                         ("ads", self._ads), ("digest", self._digest), ("cleanup", self._cleanup)):
            try:
                report[name] = fn(now)
            except Exception as exc:  # noqa: BLE001 - một bước lỗi không làm dừng cả hệ thống
                self._error(f"{name}: {type(exc).__name__}: {exc}")
                report[name] = f"lỗi: {exc}"
        return report

    # ------------------------------------------------------------------ 1. thanh toán
    def _payments(self, now: float) -> int:
        if not self.payments:
            return 0
        txs = self.payments.fetch()
        codes = [o.code for o in self.orders.all()]
        matched = 0
        for tx in txs:
            if self.orders.tx_seen(tx.id):
                continue
            self.orders.mark_tx(tx.id)
            code = find_code(tx.content, codes)
            if not code:
                guess = self._guess_order(tx, now)
                if guess is not None and _sender_matches(guess.customer_name, tx.content):
                    self.orders.event(guess, f"khớp giao dịch thiếu mã đơn theo số tiền và tên người chuyển: {tx.content[:80]}")
                    self._record_payment(guess, tx, now)
                    matched += 1
                    continue
                self._count("unmatched_tx")
                if guess is not None:  # có thể là khách quên ghi mã: nhờ chủ sở hữu xác nhận một lần
                    self._ask_owner_to_match(guess, tx, now)
                continue  # tiền không có mã đơn: không phải doanh thu kinh doanh, không ghi sổ
            self._record_payment(self.orders.get(code), tx, now)
            matched += 1
        return matched

    def _guess_order(self, tx: BankTransaction, now: float) -> Optional[Order]:
        """Đơn duy nhất đang chờ thanh toán đúng số tiền này (còn hạn báo giá, cộng 1 ngày)."""
        cands = [o for o in self.orders.by_status("quoted")
                 if o.price_vnd - o.paid_vnd == tx.amount_vnd and now <= o.quote_expires_at + 86400]
        return cands[0] if len(cands) == 1 else None

    def _ask_owner_to_match(self, order: Order, tx: BankTransaction, now: float) -> None:
        pending = dict(self.state.kv_get("unmatched_candidates", {}) or {})
        pending[order.code] = {"id": tx.id, "amount": tx.amount_vnd, "content": tx.content[:200], "ts": now}
        self.state.kv_set("unmatched_candidates", pending)
        if self.cfg.notify_email:
            self._send(self.cfg.notify_email, f"[CẦN BẠN] Tiền vào thiếu mã đơn — có thể là đơn {order.code}",
                       f"Tài khoản nhận tiền vừa nhận {T.fmt_vnd(tx.amount_vnd)}, nội dung \"{tx.content[:200]}\", "
                       f"nhưng không ghi mã đơn. Số tiền trùng với đơn {order.code} của {order.customer_name or order.customer_email}.\n\n"
                       f"Nếu đúng là khách này: bấm đúp deploy\\lenh-nhanh-windows.bat, chọn T, nhập {order.code} "
                       f"(máy Mac/Linux: automaton51 paid {order.code}). AI sẽ xử lý đơn ngay sau đó.\n"
                       f"Nếu không phải (tiền cá nhân): không cần làm gì.\n\n-- automaton51", kind="owner")

    def record_manual_payment(self, code: str, amount_vnd: Optional[int] = None) -> Order:
        """Chủ sở hữu xác nhận một khoản tiền (thiếu mã đơn) là của đơn này."""
        order = self.orders.get(code)
        if order is None:
            raise ValueError(f"Không có đơn {code}")
        pending = dict(self.state.kv_get("unmatched_candidates", {}) or {})
        cand = pending.pop(code, None)
        if amount_vnd is None and cand is None:
            raise ValueError(f"Chưa thấy giao dịch nào chờ khớp với đơn {code}. Nếu chắc chắn đã nhận tiền, ghi kèm số tiền "
                             f"(lệnh: automaton51 paid {code} --amount <số đồng>).")
        now = self.clock()
        tx = BankTransaction(id=cand["id"] if cand else f"manual:{code}:{int(now)}",
                             amount_vnd=int(amount_vnd if amount_vnd is not None else cand["amount"]),
                             content=f"chủ sở hữu xác nhận cho đơn {code}")
        self.state.kv_set("unmatched_candidates", pending)
        self._record_payment(order, tx, now)
        return self.orders.get(code)

    def _record_payment(self, order: Order, tx: BankTransaction, now: float) -> None:
        usd = D(Decimal(tx.amount_vnd) / Decimal(self.cfg.vnd_per_usd))
        self.ledger.revenue(usd, "order", f"Đơn {order.code}: {T.fmt_vnd(tx.amount_vnd)}",
                            meta={"order": order.code, "vnd": tx.amount_vnd, "tx": tx.id, "line": line_of(order.services)})
        order.paid_vnd += tx.amount_vnd
        order.paid_at = now
        self._count("paid_vnd", tx.amount_vnd)
        self.log(f"💰 +{T.fmt_vnd(tx.amount_vnd)} đơn {order.code}")
        if order.status in ("delivered", "closed", "refunded"):
            self.orders.event(order, f"nhận thêm {tx.amount_vnd} đ sau khi đã hoàn tất")
            self._escalate(order, f"Khách chuyển thêm {T.fmt_vnd(tx.amount_vnd)} cho đơn đã hoàn tất (có thể chuyển trùng): "
                                  f"hoàn lại {T.fmt_vnd(tx.amount_vnd)}.", refund_vnd=tx.amount_vnd)
            return
        if order.paid_vnd >= order.price_vnd - 1000:
            self.orders.event(order, f"đã thanh toán {order.paid_vnd} đ", status="paid")
            self._count("paid_orders")
            self._send(order.customer_email, *T.payment_received(order, self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
        else:
            self.orders.event(order, f"thanh toán thiếu: {order.paid_vnd}/{order.price_vnd}")
            self._send(order.customer_email, *T.partial_payment(order, self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)

    # ------------------------------------------------------------------ 2. hộp thư
    def _inbox(self, now: float) -> int:
        if not self.mail:
            return 0
        since = self.state.kv_get("imap_last_uid", None)
        emails, max_uid = self.mail.fetch_new(None if since is None else int(since))
        processed = list(self.state.kv_get("inbox_processed", []) or [])
        failures = dict(self.state.kv_get("inbox_failures", {}) or {})
        handled = 0
        last_ok = None if since is None else int(since)
        for em in sorted(emails, key=lambda e: e.uid):
            key = em.message_id or f"uid:{em.uid}"
            if key in processed:
                last_ok = em.uid
                continue
            try:
                if self._handle(em, now):
                    handled += 1
            except Exception as exc:  # noqa: BLE001
                failures[key] = int(failures.get(key, 0)) + 1
                self._error(f"thư {key} lỗi lần {failures[key]}: {type(exc).__name__}: {exc}")
                if failures[key] < 3:
                    self.state.kv_set("inbox_failures", failures)
                    self.state.kv_set("imap_last_uid", last_ok if last_ok is not None else max(0, em.uid - 1))
                    self.state.kv_set("inbox_processed", processed[-3000:])
                    return handled  # dừng lượt này, lần sau thử lại đúng thư này
            processed.append(key)
            failures.pop(key, None)
            last_ok = em.uid
        self.state.kv_set("inbox_failures", failures)
        self.state.kv_set("inbox_processed", processed[-3000:])
        self.state.kv_set("imap_last_uid", max_uid if not emails else max(max_uid, last_ok or 0))
        return handled

    def _handle(self, em: InboundEmail, now: float) -> bool:
        own = {self.cfg.email_address.lower(), self.cfg.email_alias.lower()}
        if em.auto_generated or not em.from_addr or em.from_addr in own:
            return False
        if not addressed_to(em, self.cfg.email_alias, self.cfg.order_code_prefix):
            return False  # thư cá nhân của chủ sở hữu: không đụng tới
        self._count("inbound")
        text = strip_quoted(em.text)
        intent = classify(em.subject, text, bool(em.attachments), self._capped_llm())
        if intent.kind == "unsubscribe":
            self.outreach.suppress(em.from_addr)
            self._count("unsubscribed")
            return True
        order = self.orders.find_by_thread([em.in_reply_to, *em.references]) or self._order_from_subject(em.subject)
        if order and order.customer_email == em.from_addr:
            self._order_reply(order, em, text, intent, now)
            return True
        name = em.from_name or given_name(em.from_addr.split("@")[0])
        contact = self.outreach.get(em.from_addr)
        if contact and contact.status in ("sent", "pending"):
            contact.replied_at = now
            contact.status = "yes" if intent.kind == "yes" else "replied"
            if intent.kind == "yes":  # lưu bằng chứng đồng ý (Luật Bảo vệ dữ liệu cá nhân: đồng ý phải kiểm chứng được)
                contact.consent = f"{int(now)}|{em.message_id}|{text[:60]}"
            self.outreach.update(contact)
            if intent.kind == "yes":
                self._count("outreach_yes")
        services = expand_services(intent.services)
        line = "B" if (contact is not None and contact.group == "G") else (line_of(services) if services else "")
        if intent.kind == "yes":
            self._reply(em, *T.services_info(name, self.cfg.business_name, self.owner, line=line or "A", sender=self.sender_block()))
        elif intent.kind == "forbidden":
            self._count("declined")
            self._reply(em, *T.declined(name, self.cfg.business_name, self.owner, intent.reason))
        elif intent.kind == "restricted":
            self._count("restricted")
            self._reply(em, *T.restricted(name, self.cfg.business_name, self.owner))
        elif intent.kind == "checklist":
            self._count("checklist")
            self._reply(em, *T.checklist(name, self.cfg.business_name, self.owner, self.checklist_text))
        elif intent.kind == "service_request" and em.attachments and services:
            missing = self._missing_formats(services, em)
            if missing:
                self._reply(em, *T.need_format(name, self.cfg.business_name, self.owner, missing))
            elif self._attachments_restricted(em):
                self._count("restricted")
                self._reply(em, *T.restricted(name, self.cfg.business_name, self.owner))
            else:
                self._new_order(em, name, intent, now)
        else:
            self._reply(em, *T.ask_details(name, self.cfg.business_name, self.owner, line=line))
        return True

    @staticmethod
    def _missing_formats(services: list[str], em: InboundEmail) -> list[tuple[str, tuple]]:
        exts = {Path(a.filename).suffix.lower() for a in em.attachments}
        return [(s, SERVICES[s]["accepts"]) for s in services if not exts & set(SERVICES[s]["accepts"])]

    @staticmethod
    def _attachments_restricted(em: InboundEmail) -> bool:
        """Dấu độ mật ở phần đầu tệp, hoặc tiêu đề tệp là hồ sơ cá nhân (kể cả tệp gõ phông .VnTime)."""
        for a in em.attachments:
            ext = Path(a.filename).suffix.lower()
            if ext == ".docx":
                text = docx_text_from_bytes(a.content, limit=6000)
            elif ext == ".txt":
                text = a.content[:6000].decode("utf-8", errors="ignore")
            else:
                continue  # bản scan: AI kiểm tra khi đọc (quy tắc 6), phát hiện thì dừng hẳn
            text = convert_plain(text)[0]
            if is_classified(text[:3000]) or is_personnel(a.filename + "\n" + text[:600]):
                return True
        return False

    def _capped_llm(self) -> Optional[Callable[[str, str], dict]]:
        if self.llm_classify is None:
            return None
        key = f"intake_llm:{_day(self.clock())}"
        if int(self.state.kv_get(key, 0) or 0) >= self.cfg.intake_llm_daily_limit:
            return None

        def call(system: str, user: str) -> dict:
            self._kv_inc(key)
            return self.llm_classify(system, user)  # type: ignore[misc]
        return call

    def _order_from_subject(self, subject: str) -> Optional[Order]:
        m = re.search(rf"\[({re.escape(self.cfg.order_code_prefix)}[A-Z0-9]{{6,}})\]", subject or "", re.I)
        return self.orders.get(m.group(1).upper()) if m else None

    def _save_attachments(self, order: Order, em: InboundEmail, sub: str = "in") -> list[str]:
        d = self._order_dir(order.code) / sub
        d.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, att in enumerate(em.attachments):
            safe = re.sub(r"[^\w.\- ]", "_", Path(att.filename).name)[:120] or f"tep_{i}"
            target = d / safe
            if target.exists():
                target = d / f"{target.stem}_{i}{target.suffix}"
            target.write_bytes(att.content)
            saved.append(str(target))
        return saved

    def _new_order(self, em: InboundEmail, name: str, intent: Intent, now: float) -> Optional[Order]:
        existing = self.orders.find_by_thread([em.message_id]) if em.message_id else None
        if existing is not None:  # thư này đã tạo đơn ở lần xử lý trước (bị lỗi giữa chừng): chỉ gửi lại báo giá
            if existing.price_vnd > 0 and existing.status == "quoted":
                self._send_quote(existing, em)
            return existing
        services = expand_services(intent.services)
        order = self.orders.create(em.from_addr, name, services, 1, [], self.cfg.quote_valid_days,
                                   notes=intent.notes, citation_style=intent.citation_style)
        order.thread_ids = [em.message_id] if em.message_id else []
        order.inputs = self._save_attachments(order, em)
        order.pages = max(1, sum(estimate_pages(Path(p)) for p in order.inputs if Path(p).suffix.lower() != ".md"))
        limit = max_pages_for(order.services, self.cfg.max_order_pages)
        if order.pages > limit:
            shutil.rmtree(self._order_dir(order.code), ignore_errors=True)
            order.inputs = []
            if line_of(order.services) == "B" and order.pages > self.cfg.max_order_pages:
                # cơ quan, khối lượng lớn: gửi phiếu đề xuất, chủ sở hữu làm hợp đồng
                self.orders.event(order, f"dự án lớn: {order.pages} trang", status="proposal")
                self._project_proposal(order, em, now)
                return None
            self.orders.event(order, f"quá lớn: {order.pages} trang", status="declined")
            self._reply(em, f"{self.cfg.business_name}: tệp quá lớn để xử lý tự động",
                        f"Chào {name},\n\nTài liệu khoảng {order.pages} trang, vượt giới hạn {limit} trang mỗi lần gửi. "
                        "Bạn chia thành các phần nhỏ hơn và gửi lại từng phần để được báo giá." + T.footer(self.cfg.business_name, self.owner))
            return None
        if order.services == ["CP"] and not any(self._has_legacy(Path(p)) for p in order.inputs):
            shutil.rmtree(self._order_dir(order.code), ignore_errors=True)
            order.inputs = []
            self.orders.event(order, "không có phông cũ để chuyển", status="declined")
            self._reply(em, f"{self.cfg.business_name}: tệp đã là Unicode",
                        f"Chào {name},\n\nHệ thống không thấy đoạn nào gõ bằng phông TCVN3 (.VnTime) hay VNI trong tệp bạn gửi: "
                        "tệp đã dùng Unicode nên không cần chuyển phông. Nếu chữ vẫn hiển thị lỗi, có thể tệp là bản scan (ảnh): "
                        "khi đó cần dịch vụ số hoá (nhận dạng chữ).\n\nBảng giá:\n" + T.price_table("B")
                        + T.footer(self.cfg.business_name, self.owner), order=order)
            return None
        order.price_vnd = quote_total(order.services, order.pages)
        if order.price_vnd == 0 and not self._free_allowed(em.from_addr, now):
            order.price_vnd = 50_000  # đã dùng lượt miễn phí: thu mức tối thiểu
        self.orders.save(order)
        if order.price_vnd == 0:
            self._use_free(em.from_addr, now)
            self.orders.event(order, "miễn phí: chuyển phông", status="paid")
            self._reply(em, *T.free_accepted(order, self.cfg.business_name, self.owner), order=order)
            self._count("free_orders")
            self.log(f"🎁 Chuyển phông miễn phí {order.code} cho {em.from_addr}")
            return order
        self._send_quote(order, em)
        self._count("quotes")
        self.log(f"🧾 Báo giá {order.code}: {T.fmt_vnd(order.price_vnd)} cho {em.from_addr}")
        return order

    @staticmethod
    def _has_legacy(path: Path) -> bool:
        if path.suffix.lower() == ".docx":
            return docx_legacy_report(path).changed
        if path.suffix.lower() == ".txt":
            return bool(convert_plain(path.read_text(encoding="utf-8", errors="ignore"))[1])
        return False

    def _free_allowed(self, email: str, now: float) -> bool:
        if int(self.state.kv_get(f"free_cp:{_day(now)}", 0) or 0) >= self.cfg.free_cp_per_day:
            return False
        last = dict(self.state.kv_get("free_cp_last", {}) or {}).get(email.lower())
        return last is None or now - float(last) >= 86400

    def _use_free(self, email: str, now: float) -> None:
        self._kv_inc(f"free_cp:{_day(now)}")
        last = dict(self.state.kv_get("free_cp_last", {}) or {})
        last[email.lower()] = now
        if len(last) > 2000:  # giữ gọn: bỏ các mục cũ nhất
            last = dict(sorted(last.items(), key=lambda kv: kv[1])[-1000:])
        self.state.kv_set("free_cp_last", last)

    def _project_proposal(self, order: Order, em: InboundEmail, now: float) -> None:
        from .proposal import make_proposal
        path = self._order_dir(order.code) / f"DE_XUAT_{order.code}.docx"
        today = time.strftime("%d/%m/%Y", time.gmtime(now + VN_OFFSET_HOURS * 3600))
        estimate = make_proposal(path, order.customer_name, self.cfg.business_name, self.owner, self.cfg.email_alias,
                                 order.pages, order.services, today, self.cfg.retention_days)
        self._reply(em, *T.project_proposal(order.customer_name, self.cfg.business_name, self.owner, order.pages, estimate,
                                            order.services), attachments=[path], order=order)
        leads = list(self.state.kv_get("leads", []) or [])[-199:]
        leads.append({"ts": now, "code": order.code, "email": em.from_addr, "pages": order.pages, "estimate": estimate,
                      "services": order.services})
        self.state.kv_set("leads", leads)
        self._count("leads")
        if self.cfg.notify_email:
            self._send(self.cfg.notify_email, *T.owner_lead(order.customer_name, em.from_addr, order.pages, estimate, order.services),
                       kind="owner")

    def _send_quote(self, order: Order, em: Optional[InboundEmail] = None) -> bool:
        due = max(0, order.price_vnd - order.paid_vnd) or order.price_vnd
        qr = vietqr_url(self.cfg.bank_id, self.cfg.bank_account_number, self.cfg.bank_account_name, due, order.code)
        subject, body = T.quote(order, self.cfg.business_name, self.owner, qr, self._bank_line(), self.cfg.retention_days)
        if em is not None:
            mid = self._reply(em, subject, body, order=order)
        else:
            mid = self._send(order.customer_email, subject, body, in_reply_to=order.thread_ids[-1] if order.thread_ids else "",
                             references=order.thread_ids)
            if mid:
                order.thread_ids.append(mid)
        order.qa = {**(order.qa or {}), "quote_sent": bool(mid)}
        self.orders.save(order)
        return bool(mid)

    def _order_reply(self, order: Order, em: InboundEmail, text: str, intent: Intent, now: float) -> None:
        if em.message_id and em.message_id not in order.thread_ids:
            order.thread_ids.append(em.message_id)
        complaint = _has_any(text, COMPLAINT_WORDS)
        within = order.delivered_at and now - order.delivered_at <= self.cfg.revision_days * 86400
        can_revise = order.status == "delivered" and within and order.revisions_used < self.cfg.revision_limit
        if complaint and order.paid_vnd > 0 and not can_revise:
            self._escalate(order, f"Khách phản hồi không hài lòng về đơn {order.code}: \"{text[:300]}\". "
                                  f"Đề xuất hoàn {T.fmt_vnd(order.paid_vnd)}.", refund_vnd=order.paid_vnd, em=em)
            return
        if order.status in ("quoted", "expired"):
            if em.attachments:
                order.inputs += self._save_attachments(order, em)
                order.pages = max(1, sum(estimate_pages(Path(p)) for p in order.inputs if Path(p).suffix.lower() != ".md"))
                from .orders import quote_total
                order.price_vnd = quote_total(order.services, order.pages)
                order.quote_expires_at = now + self.cfg.quote_valid_days * 86400
                order.status = "quoted"
                self.orders.save(order)
                self._send_quote(order, em)
            elif not (intent.kind == "yes" or len(text) < 25):  # "cảm ơn", "ok": không cần gửi lại báo giá
                self.orders.save(order)
                self._send_quote(order, em)
            else:
                self.orders.save(order)
        elif order.status in ("paid", "processing", "revision", "delivering"):
            self._reply(em, f"[{order.code}] Đang xử lý",
                        f"Chào {order.customer_name or 'bạn'},\n\nĐơn {order.code} đang được xử lý, kết quả sẽ gửi qua email này."
                        + T.footer(self.cfg.business_name, self.owner), order=order)
        elif order.status in ("delivered", "closed") and not complaint and not em.attachments and \
                (intent.kind == "yes" or not (_has_any(text, REVISION_WORDS) or len(text.strip()) >= 60)):
            # "CÓ", "cảm ơn", "đã nhận": không phải yêu cầu sửa (không tốn tiền chạy lại)
            if intent.kind == "yes":
                line = line_of(order.services)
                self.outreach.record_consent(em.from_addr, order.customer_name, "G" if line == "B" else "B",
                                             f"{int(now)}|{em.message_id}|{text[:60]}")
                self._count("outreach_yes")
                self._reply(em, *T.services_info(order.customer_name, self.cfg.business_name, self.owner, line=line,
                                                 sender=self.sender_block()), order=order)
            else:
                self.orders.save(order)
        elif can_revise:
            order.inputs += self._save_attachments(order, em, "revision")
            order.revision_notes = text[:3000]
            order.attempts = 0
            order.qa = {**(order.qa or {}), "rev_done_groups": {}}  # lần sửa mới: làm lại mọi phần theo yêu cầu
            self.orders.event(order, "khách yêu cầu sửa", status="revision")
            self._reply(em, f"[{order.code}] Đã nhận yêu cầu sửa",
                        f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận yêu cầu sửa cho đơn {order.code}. Bản sửa sẽ gửi qua email này."
                        + T.footer(self.cfg.business_name, self.owner), order=order)
        elif order.status in ("delivered", "closed"):
            self._reply(em, *T.unsupported_revision(order, self.cfg.business_name, self.owner), order=order)
        elif order.status in ("failed", "escalated", "refunded"):
            self._reply(em, *T.escalated_customer(order, self.cfg.business_name, self.owner), order=order)
        else:
            self._reply(em, *T.ask_details(order.customer_name, self.cfg.business_name, self.owner), order=order)

    def _escalate(self, order: Order, reason: str, refund_vnd: int = 0, em: Optional[InboundEmail] = None) -> None:
        order.escalation = reason
        if refund_vnd:
            order.qa = {**(order.qa or {}), "refund_vnd": int(refund_vnd)}
        self.orders.event(order, f"cần người: {reason[:200]}", status="escalated" if order.status != "failed" else "failed")
        self._count("escalated")
        if em is not None:
            self._reply(em, *T.escalated_customer(order, self.cfg.business_name, self.owner), order=order)
        self._alert_owner(order, reason, refund_vnd)

    def _alert_owner(self, order: Order, reason: str, refund_vnd: int) -> None:
        to = self.cfg.notify_email
        if not to:
            return
        action = (f"Việc cần làm (duy nhất): chuyển lại {T.fmt_vnd(refund_vnd)} cho người đã chuyển khoản với nội dung "
                  f"{order.code} (xem sao kê ngân hàng; email khách: {order.customer_email}).\n"
                  f"Sau khi chuyển, ghi sổ và báo khách: bấm đúp deploy\\lenh-nhanh-windows.bat, chọn 3, nhập {order.code}\n"
                  f"(máy Mac/Linux: automaton51 refund {order.code})"
                  if refund_vnd else "Không cần chuyển tiền. Hệ thống đã phản hồi khách.")
        self._send(to, f"[CẦN BẠN] Đơn {order.code}: hoàn tiền {T.fmt_vnd(refund_vnd)}" if refund_vnd else f"[THÔNG BÁO] Đơn {order.code}",
                   f"{reason}\n\n{action}\n\n-- automaton51", kind="owner")

    # ------------------------------------------------------------------ 3. xử lý đơn
    def _fulfill(self, now: float) -> int:
        for order in self.orders.by_status("delivering"):
            self._deliver(order, now)
        for order in self.orders.by_status("processing"):
            if now - order.updated_at > 3 * 3600:
                self.orders.event(order, "khôi phục sau gián đoạn", status="revision" if order.revision_notes else "paid")
        queue = self.orders.by_status("paid", "revision")
        local = [o for o in queue if set(o.services) <= {"CP"}]  # chuyển phông: làm tại máy, không cần AI, không tốn tiền
        for order in local:
            self._process(order, now)
        if not self.fulfiller:
            return len(local)
        done = len(local)
        for order in [o for o in queue if o not in local][: max(1, self.cfg.orders_per_tick)]:
            self.ledger.reload()
            if self.ledger.balance("operating") < PREAUTH_USD:
                growth = self.ledger.balance("growth")
                if self.cfg.allow_growth_rescue and growth > ZERO:
                    self.ledger.rescue(min(growth, PREAUTH_USD), memo=f"Cứu sinh để xử lý đơn {order.code}")
                else:
                    self._error(f"không đủ tiền vận hành để xử lý đơn {order.code}")
                    break
            try:
                self._process(order, now)
            except InfraPause:
                break  # hạ tầng có sự cố: dừng xử lý đơn ở nhịp này, thử lại nhịp sau
            done += 1
        return done

    def _infra_alert(self, kind: str, detail: str, now: float) -> None:
        self._error(f"hạ tầng ({kind}): {detail[:200]}")
        last = self.state.kv_get(f"infra_alert:{kind}", 0) or 0
        if now - float(last) < INFRA_ALERT_EVERY_S or not self.cfg.notify_email:
            return
        title, advice = INFRA_ADVICE[kind]
        prefix = "[CẦN BẠN]" if kind in ("billing", "auth") else "[THÔNG BÁO]"
        self._send(self.cfg.notify_email, f"{prefix} {title}", f"{advice}\n\nChi tiết kỹ thuật: {detail[:500]}\n\n-- automaton51",
                   kind="owner")
        self.state.kv_set(f"infra_alert:{kind}", now)

    def _unicode_inputs(self, originals: list[Path], work_dir: Path) -> tuple[list[Path], list[Path], str]:
        """Chuyển phông TCVN3/VNI sang Unicode tại máy (miễn phí, không dùng AI) trước mọi bước khác.
        Trả (đầu vào đã chuyển, các tệp đã chuyển, ghi chú cho báo cáo)."""
        out: list[Path] = []
        converted: list[Path] = []
        notes: list[str] = []
        for p in originals:
            ext = p.suffix.lower()
            if ext == ".docx" and docx_legacy_report(p).changed:
                dst = work_dir / "unicode" / f"UNICODE_{p.name}"
                rep = convert_docx(p, dst)
                kinds = " và ".join(k for k, n in (("TCVN3", rep.tcvn3), ("VNI", rep.vni)) if n)
                notes.append(f"- {p.name}: chuyển {rep.paragraphs_converted} đoạn gõ phông {kinds} sang Unicode, "
                             "đổi phông cũ (.VnTime/VNI) sang Times New Roman.")
                out.append(dst)
                converted.append(dst)
                continue
            if ext == ".txt":
                text, enc = convert_plain(p.read_text(encoding="utf-8", errors="ignore"))
                if enc:
                    dst = work_dir / "unicode" / f"UNICODE_{p.name}"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(text, encoding="utf-8")
                    notes.append(f"- {p.name}: chuyển văn bản {enc.upper()} sang Unicode.")
                    out.append(dst)
                    converted.append(dst)
                    continue
            out.append(p)
        return out, converted, "\n".join(notes)

    def _process(self, order: Order, now: float) -> None:
        is_rev = order.status == "revision"
        order.attempts += 1
        self.orders.event(order, f"xử lý lần {order.attempts}", status="processing")
        originals = [Path(p) for p in order.inputs if Path(p).exists()]  # mọi tệp khách gửi, bản mới nhất nằm cuối
        work = self._order_dir(order.code) / (f"out_r{order.revisions_used + 1}_{order.attempts}" if is_rev else f"out_{order.attempts}")
        inputs, converted, conv_note = self._unicode_inputs(originals, work)  # tệp của khách (đã chuyển Unicode nếu cần)
        delivered = dict((order.qa or {}).get("delivered_groups") or {})
        notes = order.revision_notes if is_rev else ""
        if order.attempts > 1 and (order.qa or {}).get("issues"):
            notes = (notes + "\n\nLẦN TRƯỚC BỊ LOẠI Ở KHÂU KIỂM TRA TỰ ĐỘNG VÌ: " + "; ".join(order.qa["issues"])).strip()
        groups = plan_groups(order.services)
        key = "rev_done_groups" if is_rev else "done_groups"  # lượt sửa có sổ phần-đã-đạt riêng
        done: dict[str, dict] = dict((order.qa or {}).get(key) or {})
        issues: list[str] = []
        metrics: dict[str, Any] = {}
        fatal = False
        used_ai = False
        self._current = order
        try:
            for tag, svcs in groups:
                prev = done.get(tag)
                if prev and all(Path(p).exists() for p in prev["outputs"]):
                    continue  # phần này đã đạt ở lượt trước: giữ nguyên, không tốn tiền làm lại
                if tag == "CP":
                    report = ("# Chuyển phông sang Unicode\n\n" + conv_note) if converted else \
                        "# Chuyển phông sang Unicode\n\nKhông phát hiện đoạn nào gõ bằng phông TCVN3/VNI: tệp đã là Unicode."
                    result = FulfillmentResult(outputs=list(converted), report=report)
                    qa = qa_check(["CP"], originals, result.outputs, result.report)
                else:
                    used_ai = True
                    code = order.code if len(groups) == 1 else f"{order.code}_{tag}"
                    out_dir = work if len(groups) == 1 else work / tag
                    group_inputs = list(inputs)
                    qa_inputs = list(inputs)  # luôn đối chiếu với tệp gốc của khách
                    if tag == "TA" and "TT" in order.services:
                        # bản tiếng Anh dịch đúng quyển tóm tắt vừa biên tập trong cùng đơn: phải chờ phần TT đạt trước
                        made = [Path(p) for p in (done.get("TT") or {}).get("outputs", [])
                                if Path(p).name.upper().startswith("TOM_TAT_LUAN_AN") and Path(p).exists()]
                        if not made:
                            issues.append("[TA] chờ quyển tóm tắt tiếng Việt đạt kiểm tra")
                            continue
                        group_inputs += made
                        qa_inputs += made
                    if is_rev:  # lần sửa: kèm bản đã giao của CHÍNH phần này (không lẫn tệp của phần khác)
                        prev = delivered.get(tag) or (order.outputs if len(groups) == 1 else [])
                        group_inputs += [Path(p) for p in prev
                                         if Path(p).suffix.lower() in (".docx", ".pptx", ".xlsx") and Path(p).exists()]
                    try:
                        result = self.fulfiller.run(code, svcs, group_inputs, out_dir, order.customer_notes, order.citation_style, notes)
                        qa = qa_check(svcs, qa_inputs, result.outputs, result.report)
                    except FulfillmentError as exc:
                        result, qa = None, QAResult(False, [f"lỗi xử lý: {exc}"])
                    except Exception as exc:  # noqa: BLE001
                        kind = infra_problem(exc)
                        if kind is not None:  # không phải lỗi của đơn: giữ đơn, không tính lượt, báo chủ sở hữu
                            order.attempts -= 1
                            order.qa = {**(order.qa or {}), key: done}
                            self.orders.event(order, f"tạm hoãn ({kind}): {str(exc)[:160]}", status="revision" if is_rev else "paid")
                            self._infra_alert(kind, str(exc), now)
                            raise InfraPause(kind) from exc
                        result, qa = None, QAResult(False, [f"lỗi hệ thống: {type(exc).__name__}: {exc}"])
                metrics.update({f"{tag}.{k}" if len(groups) > 1 else k: v for k, v in qa.metrics.items()})
                if qa.passed and result is not None:
                    done[tag] = {"outputs": [str(p) for p in result.outputs], "report": result.report[:8000]}
                else:
                    issues += [f"[{tag}] {i}" if len(groups) > 1 else i for i in qa.issues]
                    fatal = fatal or qa.fatal
                    if fatal:
                        break
                order.qa = {**(order.qa or {}), key: done}
                self.orders.save(order)
        finally:
            self._current = None
        if used_ai:
            self._charge_capped(D(self.cfg.code_exec_usd_per_order), "tool", f"Môi trường chạy mã đơn {order.code}",
                                {"order": order.code, "line": line_of(order.services)})
        order.qa = {"passed": not issues, "issues": issues, "metrics": metrics, key: done}
        if not issues:
            order.qa["delivered_groups"] = {tag: done[tag]["outputs"] for tag, _ in groups}
            order.outputs = [p for tag, _ in groups for p in done[tag]["outputs"]]
            if converted and "CP" not in order.services:  # khách được nhận luôn bản Unicode của tệp phông cũ
                order.outputs += [str(p) for p in converted if str(p) not in order.outputs]
            reports = [done[tag]["report"] for tag, _ in groups]
            if conv_note and "CP" not in order.services:
                reports.insert(0, "# Chuyển phông sang Unicode (làm tại máy, không dùng AI)\n\n" + conv_note)
            order.delivered_at = now
            if is_rev:
                order.revisions_used += 1
                order.revision_notes = ""
            order.attempts = 0
            order.qa["report"] = "\n\n".join(r.strip() for r in reports if r.strip())[:12000]
            if len(groups) > 1:  # gộp báo cáo từng phần thành một tệp, không đính kèm nhiều tệp báo cáo rời
                combined = work / f"BAO_CAO_{order.code}.md"
                combined.parent.mkdir(parents=True, exist_ok=True)
                combined.write_text("\n\n".join(r.strip() for r in reports if r.strip()), encoding="utf-8")
                order.outputs = [p for p in order.outputs if not Path(p).name.upper().startswith("BAO_CAO")] + [str(combined)]
            self.orders.event(order, "đã xử lý xong, chờ gửi", status="delivering")
            self._deliver(order, now)
            return
        if fatal:  # tài liệu mật / hồ sơ cá nhân: dừng hẳn, xoá tệp, hoàn tiền
            shutil.rmtree(self._order_dir(order.code), ignore_errors=True)
            order.inputs, order.outputs = [], []
            order.qa["done_groups"] = {}
            self.orders.event(order, "dừng: " + "; ".join(issues)[:200], status="failed")
            self._count("restricted")
            self._send(order.customer_email, *T.stopped_customer(order, self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
            if order.paid_vnd:
                self._escalate(order, f"Đơn {order.code} bị dừng vì phát hiện tài liệu mật hoặc hồ sơ cá nhân; đã xoá tệp.",
                               refund_vnd=order.paid_vnd)
            return
        if order.attempts >= MAX_ATTEMPTS:
            self.orders.event(order, "thất bại sau 3 lần: " + "; ".join(issues)[:300], status="failed")
            self._count("failed")
            self._send(order.customer_email, *T.failed_customer(order, self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
            if order.paid_vnd:
                self._escalate(order, f"Đơn {order.code} không đạt kiểm tra tự động sau {MAX_ATTEMPTS} lần: {'; '.join(issues)[:300]}. "
                                      f"Đã báo khách sẽ được hoàn tiền.", refund_vnd=order.paid_vnd)
            return
        self.orders.event(order, "chưa đạt kiểm tra: " + "; ".join(issues)[:300], status="revision" if is_rev else "paid")

    def _deliver(self, order: Order, now: float) -> bool:
        outputs = [Path(p) for p in order.outputs if Path(p).exists()]
        attach = [p for p in outputs if p.suffix.lower() in (".docx", ".pptx", ".md", ".pdf", ".xlsx", ".txt")]
        extra = ("Dịch vụ còn hỗ trợ số hoá bản in cũ, lập biên niên sự kiện hợp nhất của các đơn vị cũ, biên tập bản thảo lịch "
                 "sử địa phương. Nếu muốn nhận bảng giá, trả lời \"CÓ\"." if order.price_vnd == 0 else "")
        mid = self._send(order.customer_email, *T.delivery(order, self.cfg.business_name, self.owner, (order.qa or {}).get("report", ""),
                                                           extra=extra),
                         attachments=attach, in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
        if not mid:
            return False  # giữ trạng thái "delivering", lần chạy sau gửi lại
        order.thread_ids.append(mid)
        order.delivered_at = now
        self.orders.event(order, "đã giao", status="delivered")
        self._count("delivered")
        self.log(f"📦 Giao đơn {order.code} ({', '.join(order.services)})")
        return True

    # ------------------------------------------------------------------ 4. vòng đời
    def _lifecycle(self, now: float) -> int:
        n = 0
        for o in self.orders.by_status("quoted"):
            if not (o.qa or {}).get("quote_sent", True) and now <= o.quote_expires_at:
                self._send_quote(o)  # báo giá trước đó gửi lỗi: gửi lại
            if now > o.quote_expires_at:
                self.orders.event(o, "hết hạn báo giá", status="expired")
                n += 1
        for o in self.orders.by_status("delivered"):
            if now - o.delivered_at > self.cfg.revision_days * 86400:
                self.orders.event(o, "đóng đơn", status="closed")
                n += 1
        return n

    # ------------------------------------------------------------------ 5. danh bạ
    def signup_hint(self) -> str:
        return f"trả lời thư này với chữ CHECKLIST (hoặc gửi thư tới {self.cfg.email_alias} với tiêu đề CHECKLIST)"

    def _outreach(self, now: float) -> int:
        if not (self.cfg.outreach_enabled and self.mail):
            return 0
        self.outreach.expire_silent(now, self.cfg.outreach_wait_days)
        if not 8 <= _vn_hour(now) < 20:
            return 0
        key = f"outreach_sent:{_day(now)}"
        remaining = self.cfg.outreach_daily_limit - int(self.state.kv_get(key, 0) or 0)
        if remaining <= 0:
            return 0
        sent = 0
        groups = {"A": ("A", "B"), "B": ("G",)}  # ngách A: người giới thiệu + học viên; ngách B: cấp ủy, cơ quan, người biên soạn
        for _ in range(min(remaining, 5)):
            waiting = {ln: self.outreach.due(1, g) for ln, g in groups.items()}
            have = {ln for ln, lst in waiting.items() if lst}
            if not have:
                break
            ln = self._pick_line("outreach_line_credit", now, have)
            c = waiting[ln][0]
            sender = self.sender_block()
            if c.group == "G":
                subject, body = T.outreach_local_history(c.name, self.cfg.business_name, self.owner, self.owner,
                                                         self.cfg.email_alias, sender)
            elif c.group == "A":
                subject, body = T.outreach_referrer(c.name, self.cfg.business_name, self.owner, self.owner, self.signup_hint(), sender)
            else:
                subject, body = T.outreach_learner(given_name(c.name), self.cfg.business_name, self.owner, self.owner,
                                                   self.signup_hint(), sender)
            if self._send(c.email, subject, body, kind="marketing") is None:
                break
            c.status, c.sent_at = "sent", now
            self.outreach.update(c)
            self._kv_inc(key)
            self._count("outreach_sent")
            self._count(f"outreach_sent_{ln}")
            sent += 1
        return sent

    # ------------------------------------------------------------------ 6. Facebook
    def _cta(self, line: str) -> str:
        if line == "B":
            return (f"\n\nChuyển phông .VnTime/VNI sang Unicode MIỄN PHÍ (tệp Word tới {CP_FREE_PAGES} trang): gửi tệp tới "
                    f"{self.cfg.email_alias}, tiêu đề CHUYEN PHONG.")
        return f"\n\nNhận checklist miễn phí và báo giá tự động: gửi email tới {self.cfg.email_alias} (tiêu đề CHECKLIST)."

    def _facebook(self, now: float) -> int:
        if not self.facebook or not 9 <= _vn_hour(now) < 21:
            return 0
        key = f"fb_posted:{_day(now)}"
        if int(self.state.kv_get(key, 0) or 0) >= self.cfg.facebook_posts_per_day:
            return 0
        published = set(self.state.kv_get("fb_published", []) or [])
        message, post_id, line = None, None, "A"
        for p in self.catalog.posts if self.catalog is not None else []:
            if p.get("platform") == "facebook" and p.get("id") not in published:
                message, post_id = p.get("text", ""), p.get("id")
                break
        if message is None and self.line_posts:
            have = {ln for ln, _ in self.line_posts}
            line = self._pick_line("fb_line_credit", now, have)
            pool = [text for ln, text in self.line_posts if ln == line]
            idx = int(self.state.kv_get(f"fb_line_index:{line}", 0) or 0)
            message = pool[idx % len(pool)]
            self.state.kv_set(f"fb_line_index:{line}", idx + 1)
        elif message is None and self.fb_fallback_posts:
            idx = int(self.state.kv_get("fb_fallback_index", 0) or 0)
            message = self.fb_fallback_posts[idx % len(self.fb_fallback_posts)]
            self.state.kv_set("fb_fallback_index", idx + 1)
        if not message:
            return 0
        message = message.strip() + self._cta(line)
        fb_id = self.facebook.publish(message)
        if post_id:
            self.state.kv_set("fb_published", sorted(published | {post_id}))
        log = list(self.state.kv_get("fb_post_log", []) or [])[-199:]
        log.append({"id": fb_id, "line": line, "ts": now, "text": message[:200]})
        self.state.kv_set("fb_post_log", log)
        self._kv_inc(key)
        self._count("fb_posts")
        self._count(f"fb_posts_{line}")
        return 1

    # ------------------------------------------------------------------ 7. quảng cáo trả tiền (Quỹ mở rộng 49%)
    def _ads(self, now: float) -> int:
        if not (self.ads and self.cfg.ads_enabled and self.facebook):
            return 0
        if now - float(self.state.kv_get("ads_last_ts", 0) or 0) < self.cfg.ads_every_days * 86400:
            return 0
        if not 9 <= _vn_hour(now) < 21:
            return 0
        self.ledger.reload()
        vat = D(self.cfg.ads_vat_rate)
        growth_vnd = self.ledger.balance("growth") * Decimal(self.cfg.vnd_per_usd)
        budget = int(min(Decimal(self.cfg.ads_weekly_cap_vnd), growth_vnd * D(self.cfg.ads_growth_share) / (1 + vat)))
        budget -= budget % 1000
        if budget < self.cfg.ads_min_budget_vnd:
            self.state.kv_set("ads_status", f"chờ Quỹ mở rộng đủ tiền (cần ≥ {T.fmt_vnd(self.cfg.ads_min_budget_vnd)} mỗi đợt)")
            return 0
        boosted = set(self.state.kv_get("ads_boosted", []) or [])
        posts = [p for p in (self.state.kv_get("fb_post_log", []) or [])
                 if p.get("line") in self.cfg.ads_lines and p.get("id") and p["id"] not in boosted and now - float(p["ts"]) <= 21 * 86400]
        if not posts:
            self.state.kv_set("ads_status", "chưa có bài ngách A mới để chạy quảng cáo")
            return 0
        best = max(posts, key=lambda p: (post_engagement(self.facebook.get, self.facebook.version, p["id"], self.facebook.token),
                                         float(p["ts"])))
        name = f"automaton51 {_day(now)} {best['id']}"
        self.state.kv_set("ads_last_ts", now)  # ghi trước: lỗi thì chờ đợt sau, không gọi Meta liên tục
        try:
            ids = self.ads.boost(best["id"], budget, self.cfg.ads_every_days, self.cfg.vnd_per_usd, now, name,
                                 self.cfg.ads_age_min, self.cfg.ads_age_max)
        except AdsError as exc:
            self._error(f"quảng cáo: {exc}")
            self.state.kv_set("ads_status", f"lỗi: {str(exc)[:200]}")
            if self.cfg.notify_email:
                self._send(self.cfg.notify_email, "[THÔNG BÁO] Chưa chạy được quảng cáo",
                           f"Meta từ chối tạo quảng cáo: {exc}\nHệ thống thử lại ở đợt sau. Không có khoản chi nào bị ghi sổ."
                           "\n\n-- automaton51", kind="owner")
            return 0
        total = int(Decimal(budget) * (1 + vat))
        usd = D(Decimal(total) / Decimal(self.cfg.vnd_per_usd))
        self.ledger.growth_spend(min(usd, self.ledger.balance("growth")), "marketing",
                                 f"Quảng cáo Facebook {T.fmt_vnd(budget)} + VAT, {self.cfg.ads_every_days} ngày",
                                 meta={"line": best.get("line", "A"), "vnd": total, "post": best["id"], **ids})
        self.state.kv_set("ads_boosted", sorted(boosted | {best["id"]})[-200:])
        camps = list(self.state.kv_get("ads_campaigns", []) or [])[-49:]
        camps.append({"ts": now, "budget_vnd": budget, "total_vnd": total, "post": best["id"], **ids})
        self.state.kv_set("ads_campaigns", camps)
        self.state.kv_set("ads_status", f"đang chạy đợt {T.fmt_vnd(budget)} từ {_day(now)}")
        self._count("ads_vnd", total)
        if self.cfg.notify_email:
            self._send(self.cfg.notify_email, *T.ads_notice(budget, total, self.cfg.ads_every_days, best.get("text", ""),
                                                            fmt(self.ledger.balance("growth"), 2)), kind="owner")
        self.log(f"📣 Quảng cáo {T.fmt_vnd(budget)} cho bài {best['id']}")
        return 1

    # ------------------------------------------------------------------ 7. báo cáo
    def digest_text(self, now: float) -> str:
        since = float(self.state.kv_get("digest_last_ts", 0) or 0) or now - 86400
        counts: dict[str, int] = {}
        d = since
        while d <= now + 1:
            for k, v in (self.state.kv_get(f"ops_count:{_day(d)}", {}) or {}).items():
                counts[k] = counts.get(k, 0) + int(v)
            d += 86400
        b = self.ledger.balances()
        t = self.ledger.totals()
        pending = [o for o in self.orders.all() if o.status in ("escalated", "failed") and (o.qa or {}).get("refund_vnd")]
        lines = [f"BÁO CÁO {time.strftime('%d/%m/%Y', time.gmtime(now + VN_OFFSET_HOURS * 3600))} — {self.cfg.business_name}", "",
                 "Hoạt động từ lần báo cáo trước:",
                 f"  Thư khách mới: {counts.get('inbound', 0)} · Báo giá: {counts.get('quotes', 0)} · Từ chối (vi phạm): {counts.get('declined', 0)}",
                 f"  Đơn đã thanh toán: {counts.get('paid_orders', 0)} · Tiền về: {T.fmt_vnd(counts.get('paid_vnd', 0))} · Đã giao: {counts.get('delivered', 0)}",
                 f"  Thất bại: {counts.get('failed', 0)} · Cần người: {counts.get('escalated', 0)} · Giao dịch không có mã đơn (bỏ qua): {counts.get('unmatched_tx', 0)}",
                 f"  Thư xin phép gửi danh bạ: {counts.get('outreach_sent', 0)} · Đồng ý: {counts.get('outreach_yes', 0)} · Từ chối nhận: {counts.get('unsubscribed', 0)}",
                 f"  Bài Facebook: {counts.get('fb_posts', 0)} · Chuyển phông miễn phí: {counts.get('free_orders', 0)} · "
                 f"Phiếu đề xuất dự án: {counts.get('leads', 0)} · Từ chối tài liệu mật/hồ sơ cá nhân: {counts.get('restricted', 0)}",
                 f"  Quảng cáo trả tiền: {T.fmt_vnd(counts.get('ads_vnd', 0))} · Tình trạng: {self.state.kv_get('ads_status', 'tắt') or 'tắt'}",
                 "", "Hai ngách (60 ngày gần nhất; tỷ trọng bài đăng và thư giới thiệu tự chia theo lãi gộp):"]
        weights = self.line_weights(now)
        for ln, st in self.line_stats(now).items():
            lines.append(f"  {ln} — {LINES[ln]}: doanh thu {fmt(st['revenue_usd'], 2)}, chi phí AI {fmt(st['cost_usd'], 2)}, "
                         f"lãi gộp {fmt(st['margin_usd'], 2)} · báo giá {st['quotes']}, đơn đã trả {st['paid']}, "
                         f"miễn phí {st['free']} · tỷ trọng {weights[ln]:.0%}")
        lines += ["",
                 "Sổ cái (USD):",
                 f"  Quỹ CHỦ SỞ HỮU 51%: {fmt(b['owner'], 2)} (đã nhận tổng {fmt(t['owner_received'], 2)}) — tiền đã nằm trong tài khoản nhận tiền của bạn; khi chuyển phần này sang tài khoản cá nhân, ghi sổ bằng lenh-nhanh-windows.bat mục 4 (hoặc lệnh: automaton51 payout)",
                 f"  Quỹ MỞ RỘNG 49%: {fmt(b['growth'], 2)} · Ví vận hành: {fmt(b['operating'], 2)}",
                 f"  Tổng doanh thu: {fmt(t['revenue'], 2)} · Chi phí vận hành: {fmt(t['operating_costs'], 2)}", ""]
        if pending:
            lines.append("VIỆC CẦN BẠN (chỉ chuyển tiền hoàn lại):")
            for o in pending:
                lines.append(f"  - Đơn {o.code}: hoàn {T.fmt_vnd(o.qa['refund_vnd'])} cho người chuyển khoản nội dung {o.code}, rồi ghi sổ bằng lenh-nhanh-windows.bat mục 3 (hoặc lệnh: automaton51 refund {o.code})")
        else:
            lines.append("Không có việc nào cần bạn quyết định.")
        if b["operating"] < self.cfg.low_threshold:
            lines += ["", f"Lưu ý: ví vận hành còn {fmt(b['operating'], 2)}. Hãy chắc rằng tài khoản API Claude còn tiền "
                          "(https://platform.claude.com/settings/billing, nên bật Auto reload)."]
        errs = self.state.kv_get("ops_errors", []) or []
        recent = [e for e in errs if float(e[0]) >= since]
        if recent:
            lines += ["", f"Lỗi kỹ thuật gần đây ({len(recent)}, hệ thống tự thử lại):"] + [f"  - {e[1]}" for e in recent[-5:]]
        return "\n".join(lines)

    def _digest(self, now: float) -> int:
        if not self.mail or not self.cfg.notify_email:
            return 0
        today = _day(now)
        if self.state.kv_get("digest_last_date") is None:  # ngày đầu: chưa có gì để báo cáo
            self.state.kv_set("digest_last_date", today)
            self.state.kv_set("digest_last_ts", now)
            return 0
        if time.gmtime(now).tm_hour < self.cfg.digest_hour_utc or self.state.kv_get("digest_last_date") == today:
            return 0
        self._send(self.cfg.notify_email, f"[automaton51] Báo cáo ngày {today}", self.digest_text(now), kind="owner")
        self.state.kv_set("digest_last_date", today)
        self.state.kv_set("digest_last_ts", now)
        return 1

    # ------------------------------------------------------------------ 8. xoá dữ liệu quá hạn
    def _cleanup(self, now: float) -> int:
        n = 0
        for o in self.orders.all():
            if o.status in ("closed", "expired", "declined", "refunded", "proposal") and not (o.qa or {}).get("anonymized") \
                    and now - o.updated_at > self.cfg.retention_days * 86400:
                shutil.rmtree(self.orders_dir / o.code, ignore_errors=True)
                o.inputs, o.outputs, o.customer_email, o.customer_name, o.customer_notes, o.revision_notes = [], [], "", "", "", ""
                o.thread_ids = []
                o.qa = {"anonymized": True}
                self.orders.save(o)
                n += 1
        return n

    # ------------------------------------------------------------------ hoàn tiền (chủ sở hữu đã chuyển xong)
    def record_refund(self, code: str, memo: str = "") -> Order:
        order = self.orders.get(code)
        if order is None:
            raise ValueError(f"Không có đơn {code}")
        vnd = int((order.qa or {}).get("refund_vnd") or order.paid_vnd)
        usd = D(Decimal(vnd) / Decimal(self.cfg.vnd_per_usd))
        self.ledger.reload()
        if self.ledger.balance("operating") < usd and self.ledger.balance("growth") > ZERO:
            self.ledger.rescue(min(self.ledger.balance("growth"), usd - self.ledger.balance("operating")),
                               memo=f"Cứu sinh để ghi hoàn tiền đơn {code}")
        self._charge_capped(usd, "other", memo or f"Hoàn tiền đơn {code}: {T.fmt_vnd(vnd)}", {"order": code, "vnd": vnd, "refund": True})
        order.qa = {**(order.qa or {}), "refund_vnd": 0, "refunded_vnd": vnd}
        self.orders.event(order, f"đã hoàn {vnd} đ", status="refunded")
        if order.customer_email:
            self._send(order.customer_email, f"[{order.code}] Đã hoàn tiền",
                       f"Chào {order.customer_name or 'bạn'},\n\nĐã hoàn {T.fmt_vnd(vnd)} cho đơn {order.code}. Xin lỗi vì sự bất tiện."
                       + T.footer(self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
        return order

    def summary(self) -> dict[str, Any]:
        by: dict[str, int] = {}
        for o in self.orders.all():
            by[o.status] = by.get(o.status, 0) + 1
        return {"orders": by, "outreach": self.outreach.stats(),
                "pending_refunds": [o.code for o in self.orders.all() if (o.qa or {}).get("refund_vnd")],
                "last_errors": (self.state.kv_get("ops_errors", []) or [])[-3:]}


def build_operations(state: StateDir, cfg: Config, ledger: Ledger, catalog: Catalog, clock: Callable[[], float],
                     log: Callable[[str], None] = print) -> Operations:
    """Dựng bộ vận hành thật từ cấu hình + khoá trong biến môi trường. Thiếu khoá nào thì tắt phần đó."""
    from . import secrets as S
    from .mail import GmailClient
    from .payments import InboxSource, SePaySource

    mail = None
    if cfg.email_address and S.get(S.ENV_EMAIL_PASSWORD):
        mail = GmailClient(cfg.email_address, S.get(S.ENV_EMAIL_PASSWORD), cfg.email_alias, cfg.order_code_prefix,
                           cfg.imap_host, cfg.imap_port, cfg.smtp_host, cfg.smtp_port, from_name=cfg.business_name)
    payments = None
    if cfg.payment_provider == "sepay" and S.get(S.ENV_SEPAY_TOKEN):
        payments = SePaySource(S.get(S.ENV_SEPAY_TOKEN), cfg.bank_account_number)
    elif cfg.payment_provider == "webhook" or S.get(S.ENV_SEPAY_WEBHOOK_KEY):
        payments = InboxSource(lambda: state.read_jsonl(state.root / "payments_inbox.jsonl"))
    facebook = None
    if cfg.facebook_page_id and S.get(S.ENV_FACEBOOK_TOKEN):
        facebook = FacebookPublisher(cfg.facebook_page_id, S.get(S.ENV_FACEBOOK_TOKEN), cfg.graph_api_version)
    ads = None
    if cfg.ads_enabled and cfg.ad_account_id and S.get(S.ENV_META_ADS):
        ads = MetaAds(cfg.ad_account_id, S.get(S.ENV_META_ADS), cfg.graph_api_version)
    ops = Operations(state, cfg, ledger, catalog, clock, mail=mail, payments=payments, facebook=facebook, log=log, ads=ads)
    if S.get(S.ENV_ANTHROPIC):
        try:
            import anthropic
            from .fulfillment import ClaudeFulfiller
            from .intake import claude_json_caller
            client = anthropic.Anthropic()
            ops.fulfiller = ClaudeFulfiller(client, cfg.fulfillment_model, cfg.fulfillment_effort,
                                            ops.charge_fn("Xử lý đơn (Claude)"), enable_fallbacks=cfg.enable_fallbacks)
            ops.llm_classify = claude_json_caller(client, cfg.intake_model, cfg.intake_effort, ops.charge_fn("Đọc thư khách (Claude)"))
        except ImportError:
            log("⚠ chưa cài anthropic SDK: pip install anthropic")
    return ops
