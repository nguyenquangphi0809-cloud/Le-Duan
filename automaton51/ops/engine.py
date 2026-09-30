"""Bộ điều phối vận hành tự động. Mỗi lần chạy (mặc định 2 phút một lần, trong nhịp tim):

  1. dò tiền về -> khớp mã đơn -> ghi doanh thu (VND -> USD) -> báo khách
  2. đọc thư mới gửi tới địa chỉ kinh doanh -> trả lời / báo giá / từ chối / nhận yêu cầu sửa
  3. xử lý đơn đã thanh toán bằng Claude -> kiểm tra chất lượng tự động -> giao hàng
  4. hết hạn báo giá, đóng đơn quá hạn sửa
  5. gửi thư xin phép cho danh bạ (tối đa N thư/ngày, 8–20 giờ giờ Việt Nam)
  6. đăng bài lên Trang Facebook (nếu có token)
  7. gửi báo cáo hằng ngày cho chủ sở hữu
  8. xoá dữ liệu khách quá hạn lưu trữ

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
from .docx_tools import QAResult, qa_check
from .facebook import FacebookPublisher, launch_kit_posts
from .fulfillment import FulfillmentError
from .intake import COMPLAINT_WORDS, Intent, _has_any, classify, fold
from .mail import InboundEmail, MailClient, OutboundEmail, addressed_to, strip_quoted
from .orders import Order, OrderStore, estimate_pages
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
                 fb_fallback_posts: Optional[list[str]] = None):
        self.state, self.cfg, self.ledger, self.catalog, self.clock = state, cfg, ledger, catalog, clock
        self.mail, self.payments, self.fulfiller, self.llm_classify, self.facebook = mail, payments, fulfiller, llm_classify, facebook
        self.log = log
        self.orders = OrderStore(state, clock, cfg.order_code_prefix)
        self.outreach = OutreachStore(state, clock)
        if checklist_text is None:
            try:
                checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8")
            except OSError:
                checklist_text = "Checklist đang được cập nhật."
        self.checklist_text = checklist_text
        self.fb_fallback_posts = fb_fallback_posts if fb_fallback_posts is not None else launch_kit_posts(FB_POSTS_PATH)
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
        return self._charge_capped(cost, "inference", memo, {"model": model, **{k: int(v) for k, v in usage.items()}})

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
                         ("digest", self._digest), ("cleanup", self._cleanup)):
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
                            meta={"order": order.code, "vnd": tx.amount_vnd, "tx": tx.id})
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
            self.outreach.update(contact)
            if intent.kind == "yes":
                self._count("outreach_yes")
        if intent.kind == "yes":
            self._reply(em, *T.services_info(name, self.cfg.business_name, self.owner))
        elif intent.kind == "forbidden":
            self._count("declined")
            self._reply(em, *T.declined(name, self.cfg.business_name, self.owner, intent.reason))
        elif intent.kind == "checklist":
            self._count("checklist")
            self._reply(em, *T.checklist(name, self.cfg.business_name, self.owner, self.checklist_text))
        elif intent.kind == "service_request" and em.attachments and intent.services:
            exts = {Path(a.filename).suffix.lower() for a in em.attachments}
            needs_docx = any(sv in intent.services for sv in ("DF", "TK", "HD"))
            if (needs_docx and ".docx" not in exts) or not exts & {".docx", ".pdf"}:
                self._reply(em, f"{self.cfg.business_name}: cần tệp Word (.docx)",
                            f"Chào {name},\n\nĐể xử lý tự động, bạn gửi lại bản thảo dạng Word .docx"
                            + ("" if needs_docx else " hoặc PDF")
                            + ". Tệp .doc đời cũ bạn mở bằng Word rồi chọn Lưu thành .docx.\n\nBảng giá:\n" + T.price_table()
                            + T.footer(self.cfg.business_name, self.owner))
            else:
                self._new_order(em, name, intent, now)
        else:
            self._reply(em, *T.ask_details(name, self.cfg.business_name, self.owner))
        return True

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
            self._send_quote(existing, em)
            return existing
        order = self.orders.create(em.from_addr, name, intent.services, 1, [], self.cfg.quote_valid_days,
                                   notes=intent.notes, citation_style=intent.citation_style)
        order.thread_ids = [em.message_id] if em.message_id else []
        order.inputs = self._save_attachments(order, em)
        order.pages = max(1, sum(estimate_pages(Path(p)) for p in order.inputs if Path(p).suffix.lower() != ".md"))
        if order.pages > self.cfg.max_order_pages:
            shutil.rmtree(self._order_dir(order.code), ignore_errors=True)
            order.inputs = []
            self.orders.event(order, f"quá lớn: {order.pages} trang", status="declined")
            self._reply(em, f"{self.cfg.business_name}: tệp quá lớn để xử lý tự động",
                        f"Chào {name},\n\nBản thảo khoảng {order.pages} trang, vượt giới hạn {self.cfg.max_order_pages} trang của hệ thống. "
                        "Bạn chia thành các phần nhỏ hơn và gửi lại từng phần để được báo giá." + T.footer(self.cfg.business_name, self.owner))
            return None
        from .orders import quote_total
        order.price_vnd = quote_total(order.services, order.pages)
        self.orders.save(order)
        self._send_quote(order, em)
        self._count("quotes")
        self.log(f"🧾 Báo giá {order.code}: {T.fmt_vnd(order.price_vnd)} cho {em.from_addr}")
        return order

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
        elif can_revise:
            order.inputs += self._save_attachments(order, em, "revision")
            order.revision_notes = text[:3000]
            order.attempts = 0
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
        if not self.fulfiller:
            return 0
        for order in self.orders.by_status("delivering"):
            self._deliver(order, now)
        for order in self.orders.by_status("processing"):
            if now - order.updated_at > 3 * 3600:
                self.orders.event(order, "khôi phục sau gián đoạn", status="revision" if order.revision_notes else "paid")
        done = 0
        for order in self.orders.by_status("paid", "revision")[: max(1, self.cfg.orders_per_tick)]:
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

    def _process(self, order: Order, now: float) -> None:
        is_rev = order.status == "revision"
        order.attempts += 1
        self.orders.event(order, f"xử lý lần {order.attempts}", status="processing")
        originals = [Path(p) for p in order.inputs if Path(p).exists()]  # mọi tệp khách gửi, bản mới nhất nằm cuối
        inputs = [Path(p) for p in order.inputs if Path(p).exists()]
        if is_rev and order.outputs:
            main = [Path(p) for p in order.outputs if Path(p).suffix.lower() in (".docx", ".pptx") and Path(p).exists()]
            inputs += main
        out_dir = self._order_dir(order.code) / (f"out_r{order.revisions_used + 1}_{order.attempts}" if is_rev else f"out_{order.attempts}")
        notes = order.revision_notes if is_rev else ""
        if order.attempts > 1 and (order.qa or {}).get("issues"):
            notes = (notes + "\n\nLẦN TRƯỚC BỊ LOẠI Ở KHÂU KIỂM TRA TỰ ĐỘNG VÌ: " + "; ".join(order.qa["issues"])).strip()
        result = None
        try:
            result = self.fulfiller.run(order.code, order.services, inputs, out_dir, order.customer_notes,
                                        order.citation_style, notes)
            qa = qa_check(order.services, originals, result.outputs, result.report)
        except FulfillmentError as exc:
            qa = QAResult(False, [f"lỗi xử lý: {exc}"])
        except Exception as exc:  # noqa: BLE001
            kind = infra_problem(exc)
            if kind is not None:  # không phải lỗi của đơn: giữ đơn, không tính lượt, báo chủ sở hữu
                order.attempts -= 1
                self.orders.event(order, f"tạm hoãn ({kind}): {str(exc)[:160]}", status="revision" if is_rev else "paid")
                self._infra_alert(kind, str(exc), now)
                raise InfraPause(kind) from exc
            qa = QAResult(False, [f"lỗi hệ thống: {type(exc).__name__}: {exc}"])
        self._charge_capped(D(self.cfg.code_exec_usd_per_order), "tool", f"Môi trường chạy mã đơn {order.code}")
        order.qa = {"passed": qa.passed, "issues": qa.issues, "metrics": qa.metrics}
        if qa.passed and result is not None:
            order.outputs = [str(p) for p in result.outputs]
            order.delivered_at = now
            if is_rev:
                order.revisions_used += 1
                order.revision_notes = ""
            order.attempts = 0
            order.qa["report"] = result.report[:8000]
            self.orders.event(order, "đã xử lý xong, chờ gửi", status="delivering")
            self._deliver(order, now)
            return
        if order.attempts >= MAX_ATTEMPTS:
            self.orders.event(order, "thất bại sau 3 lần: " + "; ".join(qa.issues)[:300], status="failed")
            self._count("failed")
            self._send(order.customer_email, *T.failed_customer(order, self.cfg.business_name, self.owner),
                       in_reply_to=order.thread_ids[-1] if order.thread_ids else "", references=order.thread_ids)
            self._escalate(order, f"Đơn {order.code} không đạt kiểm tra tự động sau {MAX_ATTEMPTS} lần: {'; '.join(qa.issues)[:300]}. "
                                  f"Đã báo khách sẽ được hoàn tiền.", refund_vnd=order.paid_vnd)
            return
        self.orders.event(order, "chưa đạt kiểm tra: " + "; ".join(qa.issues)[:300], status="revision" if is_rev else "paid")

    def _deliver(self, order: Order, now: float) -> bool:
        outputs = [Path(p) for p in order.outputs if Path(p).exists()]
        attach = [p for p in outputs if p.suffix.lower() in (".docx", ".pptx", ".md", ".pdf", ".xlsx")]
        mid = self._send(order.customer_email, *T.delivery(order, self.cfg.business_name, self.owner, (order.qa or {}).get("report", "")),
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
        for c in self.outreach.due(min(remaining, 5)):
            if c.group == "A":
                subject, body = T.outreach_referrer(c.name, self.cfg.business_name, self.owner, self.owner, self.signup_hint())
            else:
                subject, body = T.outreach_learner(given_name(c.name), self.cfg.business_name, self.owner, self.owner, self.signup_hint())
            if self._send(c.email, subject, body, kind="marketing") is None:
                break
            c.status, c.sent_at = "sent", now
            self.outreach.update(c)
            self._kv_inc(key)
            self._count("outreach_sent")
            sent += 1
        return sent

    # ------------------------------------------------------------------ 6. Facebook
    def _facebook(self, now: float) -> int:
        if not self.facebook or not 9 <= _vn_hour(now) < 21:
            return 0
        key = f"fb_posted:{_day(now)}"
        if int(self.state.kv_get(key, 0) or 0) >= self.cfg.facebook_posts_per_day:
            return 0
        published = set(self.state.kv_get("fb_published", []) or [])
        message, post_id = None, None
        for p in self.catalog.posts:
            if p.get("platform") == "facebook" and p.get("id") not in published:
                message, post_id = p.get("text", ""), p.get("id")
                break
        if message is None and self.fb_fallback_posts:
            idx = int(self.state.kv_get("fb_fallback_index", 0) or 0)
            message = self.fb_fallback_posts[idx % len(self.fb_fallback_posts)]
            self.state.kv_set("fb_fallback_index", idx + 1)
        if not message:
            return 0
        message = message.strip() + f"\n\nNhận checklist miễn phí và báo giá tự động: gửi email tới {self.cfg.email_alias} (tiêu đề CHECKLIST)."
        self.facebook.publish(message)
        if post_id:
            self.state.kv_set("fb_published", sorted(published | {post_id}))
        self._kv_inc(key)
        self._count("fb_posts")
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
                 f"  Bài Facebook: {counts.get('fb_posts', 0)}", "",
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
            if o.status in ("closed", "expired", "declined", "refunded") and not (o.qa or {}).get("anonymized") \
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
    ops = Operations(state, cfg, ledger, catalog, clock, mail=mail, payments=payments, facebook=facebook, log=log)
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
