"""Email qua Gmail (IMAP đọc, SMTP gửi) bằng mật khẩu ứng dụng. Chỉ thư viện chuẩn.

An toàn cho hộp thư cá nhân:
  * chỉ tải nội dung những thư gửi tới ĐỊA CHỈ KINH DOANH (alias) hoặc có mã đơn trong tiêu đề;
    thư cá nhân chỉ được đọc tiêu đề TO/CC/SUBJECT để lọc, không tải nội dung;
  * dùng BODY.PEEK nên không đánh dấu "đã đọc";
  * lần chạy đầu chỉ ghi mốc UID hiện tại, không xử lý thư cũ;
  * bỏ qua thư tự động (Auto-Submitted, Precedence bulk, mailer-daemon, noreply) để tránh vòng lặp.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import html as _html
import imaplib
import re
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional, Protocol

ALLOWED_ATTACHMENT_EXT = {".docx", ".doc", ".pdf", ".txt", ".md", ".rtf", ".odt", ".pptx"}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
AUTO_SENDER_RE = re.compile(r"(mailer-daemon|postmaster|no-?reply|do-?not-?reply|notifications?@)", re.I)


@dataclass
class Attachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass
class InboundEmail:
    uid: int
    message_id: str
    from_addr: str
    from_name: str
    to_addrs: list[str]
    subject: str
    text: str
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    received_at: float = 0.0
    auto_generated: bool = False


@dataclass
class OutboundEmail:
    to: str
    subject: str
    text: str
    attachments: list[Path] = field(default_factory=list)
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    message_id: str = ""


class MailClient(Protocol):
    def fetch_new(self, since_uid: Optional[int]) -> tuple[list[InboundEmail], int]: ...
    def send(self, msg: OutboundEmail) -> str: ...


# ----------------------------------------------------------------------------- tiện ích
def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = _html.unescape(raw)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", raw)).strip()


def strip_quoted(text: str) -> str:
    """Bỏ phần trích dẫn thư cũ ("On ... wrote:", "Vào ... đã viết:", dòng bắt đầu bằng '>')."""
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(On .+wrote:|Vào .+(đã viết|viết):|-----\s*Original Message|Từ:\s.+\n?)", line):
            break
        if line.strip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def parse_message(raw: bytes, uid: int = 0) -> InboundEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from_name, from_addr = email.utils.parseaddr(str(msg.get("From", "")))
    tos = _recipients(msg)
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError):
            content = part.get_payload(decode=True).decode("utf-8", errors="replace") if part.get_payload(decode=True) else ""
        body = content if part.get_content_type() == "text/plain" else html_to_text(content)
    attachments: list[Attachment] = []
    for att in msg.iter_attachments():
        name = att.get_filename() or ""
        if not name or Path(name).suffix.lower() not in ALLOWED_ATTACHMENT_EXT:
            continue
        data = att.get_payload(decode=True) or b""
        if 0 < len(data) <= MAX_ATTACHMENT_BYTES:
            attachments.append(Attachment(filename=Path(name).name, content=data, content_type=att.get_content_type()))
    auto = (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no")
            or str(msg.get("Precedence", "")).lower() in ("bulk", "junk", "list", "auto_reply")
            or bool(msg.get("X-Autoreply")) or bool(msg.get("X-Autorespond")) or bool(msg.get("X-Automaton51"))
            or bool(AUTO_SENDER_RE.search(from_addr or "")))
    try:
        received = email.utils.parsedate_to_datetime(str(msg.get("Date"))).timestamp()
    except (TypeError, ValueError):
        received = time.time()
    refs = str(msg.get("References", "")).split()
    return InboundEmail(uid=uid, message_id=str(msg.get("Message-ID", "")).strip(), from_addr=(from_addr or "").lower(),
                        from_name=from_name or "", to_addrs=[t.lower() for t in tos], subject=str(msg.get("Subject", "")),
                        text=body or "", in_reply_to=str(msg.get("In-Reply-To", "")).strip(), references=refs,
                        attachments=attachments, received_at=received, auto_generated=auto)


EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _recipients(msg) -> list[str]:
    """Địa chỉ người nhận từ To/Cc/Delivered-To. Gọi getaddresses TỪNG giá trị khác rỗng (Python 3.11+ ở chế độ
    strict trả về rỗng nếu danh sách có phần tử trống), và dự phòng bằng regex."""
    out: list[str] = []
    for header in ("To", "Cc", "Delivered-To"):
        for value in msg.get_all(header, []) or []:
            value = str(value).strip()
            if not value:
                continue
            found = [a for _, a in email.utils.getaddresses([value]) if a and "@" in a]
            out += found or EMAIL_RE.findall(value)
    seen: list[str] = []
    for a in out:
        a = a.lower()
        if a not in seen:
            seen.append(a)
    return seen


def build_message(out: OutboundEmail, from_addr: str, from_name: str, reply_to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((from_name, from_addr))
    msg["To"] = out.to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = out.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    domain = from_addr.split("@")[-1] if "@" in from_addr else "automaton51.local"
    out.message_id = out.message_id or f"<{uuid.uuid4().hex}@{domain}>"
    msg["Message-ID"] = out.message_id
    msg["X-Automaton51"] = "1"
    msg["Auto-Submitted"] = "auto-replied" if out.in_reply_to else "auto-generated"
    if out.in_reply_to:
        msg["In-Reply-To"] = out.in_reply_to
        msg["References"] = " ".join([*out.references, out.in_reply_to]).strip()
    msg.set_content(out.text)
    for path in out.attachments:
        data = Path(path).read_bytes()
        maintype, subtype = _guess_type(Path(path).name)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(path).name)
    return msg


def _guess_type(name: str) -> tuple[str, str]:
    ext = Path(name).suffix.lower()
    return {
        ".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".pptx": ("application", "vnd.openxmlformats-officedocument.presentationml.presentation"),
        ".pdf": ("application", "pdf"), ".md": ("text", "markdown"), ".txt": ("text", "plain"),
        ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }.get(ext, ("application", "octet-stream"))


def addressed_to(em: InboundEmail, alias: str, code_prefix: str) -> bool:
    alias = (alias or "").lower()
    if alias and any(alias == t for t in em.to_addrs):
        return True
    return bool(re.search(rf"\[{re.escape(code_prefix)}[A-Z0-9]{{6,}}\]", em.subject or "", re.I))


# ----------------------------------------------------------------------------- Gmail
class GmailClient:
    def __init__(self, address: str, app_password: str, alias: str, code_prefix: str,
                 imap_host: str = "imap.gmail.com", imap_port: int = 993,
                 smtp_host: str = "smtp.gmail.com", smtp_port: int = 465,
                 from_name: str = "", timeout: int = 30):
        self.address, self.password, self.alias = address, app_password, alias
        self.code_prefix = code_prefix
        self.imap_host, self.imap_port, self.smtp_host, self.smtp_port = imap_host, imap_port, smtp_host, smtp_port
        self.from_name = from_name or address
        self.timeout = timeout

    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ssl.create_default_context(), timeout=self.timeout)
        conn.login(self.address, self.password)
        conn.select("INBOX", readonly=True)
        return conn

    def check_login(self) -> str:
        conn = self._imap()
        try:
            typ, data = conn.uid("SEARCH", None, "ALL")
            n = len(data[0].split()) if data and data[0] else 0
            return f"IMAP OK ({n} thư trong INBOX)"
        finally:
            _close(conn)

    def check_smtp(self) -> str:
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl.create_default_context(), timeout=self.timeout) as s:
            s.login(self.address, self.password)
        return "SMTP OK"

    def fetch_new(self, since_uid: Optional[int]) -> tuple[list[InboundEmail], int]:
        conn = self._imap()
        try:
            typ, st = conn.status("INBOX", "(UIDNEXT)")
            m = re.search(rb"UIDNEXT (\d+)", st[0] if st and isinstance(st[0], bytes) else b"")
            uidnext = int(m.group(1)) if m else 0
            if since_uid is None or (uidnext and since_uid >= uidnext):
                return [], max(0, uidnext - 1)  # lần đầu (hoặc hộp thư bị đánh số lại): chỉ ghi mốc, không đọc thư cũ
            typ, data = conn.uid("SEARCH", None, f"UID {since_uid + 1}:*")
            uids = [int(x) for x in (data[0].split() if data and data[0] else [])]
            new_uids = sorted(u for u in uids if u > since_uid)[:50]
            out: list[InboundEmail] = []
            for uid in new_uids:
                typ, hdr = conn.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (TO CC DELIVERED-TO SUBJECT)])")
                raw_hdr = b"".join(p[1] for p in hdr if isinstance(p, tuple))
                probe = parse_message(raw_hdr + b"\r\n", uid)
                if not addressed_to(probe, self.alias, self.code_prefix):
                    continue  # thư cá nhân: không tải nội dung
                typ, full = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = b"".join(p[1] for p in full if isinstance(p, tuple))
                out.append(parse_message(raw, uid))
            return out, max(new_uids) if new_uids else since_uid
        finally:
            _close(conn)

    def send(self, msg: OutboundEmail) -> str:
        em = build_message(msg, self.address, self.from_name, self.alias)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl.create_default_context(), timeout=self.timeout) as s:
            s.login(self.address, self.password)
            s.send_message(em)
        return msg.message_id


def _close(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- giả lập cho test/mô phỏng
class FakeMailClient:
    def __init__(self):
        self.inbox: list[InboundEmail] = []
        self.sent: list[OutboundEmail] = []
        self._uid = 0

    def deliver(self, from_addr: str, to: str, subject: str, text: str, attachments: Iterable[Attachment] = (),
                in_reply_to: str = "", from_name: str = "", headers_auto: bool = False) -> InboundEmail:
        self._uid += 1
        em = InboundEmail(uid=self._uid, message_id=f"<in{self._uid}@test>", from_addr=from_addr.lower(), from_name=from_name,
                          to_addrs=[to.lower()], subject=subject, text=text, in_reply_to=in_reply_to,
                          references=[in_reply_to] if in_reply_to else [], attachments=list(attachments),
                          received_at=time.time(), auto_generated=headers_auto)
        self.inbox.append(em)
        return em

    def fetch_new(self, since_uid: Optional[int]) -> tuple[list[InboundEmail], int]:
        max_uid = self._uid
        if since_uid is None:
            return [], max_uid
        return [m for m in self.inbox if m.uid > since_uid], max_uid

    def send(self, msg: OutboundEmail) -> str:
        msg.message_id = msg.message_id or f"<out{len(self.sent) + 1}@test>"
        self.sent.append(msg)
        return msg.message_id
