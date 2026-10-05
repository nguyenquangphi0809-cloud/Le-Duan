"""Khai thác danh bạ đúng luật, không dùng số điện thoại.

Nghị định 91/2020: chỉ gửi quảng cáo khi đã được đồng ý; được gửi MỘT thư xin phép duy nhất,
người nhận từ chối hoặc im lặng thì không gửi thêm. Luật Bảo vệ dữ liệu cá nhân 2025: chỉ lưu
dữ liệu tối thiểu (tên, email, nhóm, trạng thái); KHÔNG lưu số điện thoại; danh bạ không gửi cho AI.
"""
from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..state import StateDir, file_lock
from .intake import fold

LEARNER = ["học viên", "hoc vien", "hv ", "nghiên cứu sinh", "nghien cuu sinh", "ncs", "cao học", "cao hoc", "sinh viên",
           "sinh vien", "phd student", "master student", "graduate student", "thạc sĩ khoá", "k2"]
STAFF = ["giảng viên", "giang vien", "gv.", "ts.", "tiến sĩ", "tien si", "pgs", "gs.", "giáo sư", "giao su", "trưởng khoa",
         "phó khoa", "bộ môn", "bo mon", "biên tập", "bien tap", "tạp chí", "tap chi", "nghiên cứu viên", "lecturer", "professor",
         "editor", "researcher", "dr."]
# Cấp ủy, chính quyền, hội nghề nghiệp, bảo tàng, lưu trữ: khách của ngách B (sử liệu địa phương)
LOCAL_GOV = ["đảng ủy", "đảng uỷ", "dang uy", "huyện ủy", "huyện uỷ", "tỉnh ủy", "tỉnh uỷ", "thành ủy", "thành uỷ", "ubnd",
             "ủy ban nhân dân", "uỷ ban nhân dân", "uy ban nhan dan", "hđnd", "tuyên giáo", "tuyen giao", "dân vận",
             "văn phòng đảng", "mặt trận tổ quốc", "cựu chiến binh", "hội khoa học lịch sử", "hoi khoa hoc lich su",
             "bảo tàng", "bao tang", "lưu trữ", "luu tru", "di tích", "di tich", "phòng văn hóa", "phòng văn hoá",
             "bí thư", "bi thu", "chánh văn phòng", "biên soạn lịch sử", "bien soan lich su", "lịch sử đảng bộ"]
ACADEMIC_ORG = ["đại học", "dai hoc", "học viện", "hoc vien", "trường", "truong", "viện", "vien ", "university", "institute",
                "academy", "college", "khoa "]


@dataclass
class Contact:
    email: str
    name: str
    group: str            # A người giới thiệu | B khách tiềm năng quen | G cấp ủy, cơ quan, người biên soạn sử (ngách B) | C không gửi
    status: str = "pending"   # pending | sent | yes | no | replied | no_response
    sent_at: float = 0.0
    replied_at: float = 0.0
    consent: str = ""     # bằng chứng đồng ý nhận quảng cáo: "thời điểm|Message-ID|trích lời trả lời"


def classify_contact(name: str, email: str, org: str, title: str, labels: str, notes: str) -> str:
    blob = " ".join([name, org, title, labels, notes]).lower() + " "
    fblob = fold(blob)
    domain = email.split("@")[-1].lower() if "@" in email else ""

    def has(words: Iterable[str]) -> bool:
        return any(w in blob or fold(w) in fblob for w in words)

    if has(LEARNER):
        return "B"
    if has(LOCAL_GOV) or domain.endswith(".gov.vn") or domain.endswith("dcs.vn"):
        return "G"
    if has(STAFF):
        return "A"
    if domain.endswith(".edu.vn") or domain.endswith(".edu") or ".ac." in domain or has(ACADEMIC_ORG):
        return "A"
    return "C"


def _pick(row: dict, *names: str) -> str:
    for n in names:
        for key, value in row.items():
            if key and key.strip().lower() == n.lower() and value and value.strip():
                return value.strip()
    return ""


def parse_contacts_csv(text: str) -> list[dict]:
    """Đọc CSV xuất từ Google Contacts (định dạng mới và cũ). Chỉ lấy tên, email, tổ chức, chức danh, nhãn, ghi chú."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    for row in reader:
        name = _pick(row, "Name") or " ".join(x for x in (
            _pick(row, "First Name", "Given Name"), _pick(row, "Middle Name", "Additional Name"),
            _pick(row, "Last Name", "Family Name")) if x)
        email = ""
        for key, value in row.items():
            if key and re.match(r"^e-?mail( address| \d+ - value)?$", key.strip(), re.I) and value and "@" in value:
                email = value.split(":::")[0].strip().lower()
                break
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            continue
        out.append({"name": name.strip() or email.split("@")[0], "email": email,
                    "org": _pick(row, "Organization Name", "Organization 1 - Name"),
                    "title": _pick(row, "Organization Title", "Organization 1 - Title"),
                    "labels": _pick(row, "Labels", "Group Membership"), "notes": _pick(row, "Notes")})
    return out


class OutreachStore:
    def __init__(self, state: StateDir, clock=time.time):
        self.state = state
        self.clock = clock
        self.path = state.root / "outreach.json"

    def _load(self) -> dict:
        data = self.state.read_json(self.path, None) or {}
        data.setdefault("contacts", {})
        data.setdefault("suppressed", [])
        return data

    def _save(self, data: dict) -> None:
        self.state.write_json(self.path, data)

    def import_rows(self, rows: list[dict], own_addresses: Iterable[str] = ()) -> dict[str, int]:
        own = {a.lower() for a in own_addresses if a}
        counts = {"A": 0, "B": 0, "G": 0, "C": 0, "skipped": 0}
        with file_lock(self.state.lock_path):
            data = self._load()
            for r in rows:
                email = r["email"].lower()
                if email in own or email in data["contacts"] or email in data["suppressed"]:
                    counts["skipped"] += 1
                    continue
                group = classify_contact(r["name"], email, r.get("org", ""), r.get("title", ""), r.get("labels", ""), r.get("notes", ""))
                data["contacts"][email] = Contact(email=email, name=r["name"][:80], group=group).__dict__
                counts[group] += 1
            self._save(data)
        return counts

    def get(self, email: str) -> Optional[Contact]:
        d = self._load()["contacts"].get((email or "").lower())
        return Contact(**{k: v for k, v in d.items() if k in Contact.__dataclass_fields__}) if d else None

    def update(self, contact: Contact) -> None:
        with file_lock(self.state.lock_path):
            data = self._load()
            data["contacts"][contact.email] = contact.__dict__
            self._save(data)

    def record_consent(self, email: str, name: str, group: str, consent: str) -> None:
        """Người chưa có trong danh bạ (vd: khách nhận chuyển phông miễn phí) trả lời đồng ý nhận thông tin."""
        email = (email or "").lower()
        with file_lock(self.state.lock_path):
            data = self._load()
            if email in data["suppressed"]:
                return
            c = data["contacts"].get(email) or Contact(email=email, name=(name or email.split("@")[0])[:80], group=group).__dict__
            c.update({"status": "yes", "consent": consent, "replied_at": float(self.clock())})
            data["contacts"][email] = c
            self._save(data)

    def suppress(self, email: str) -> None:
        with file_lock(self.state.lock_path):
            data = self._load()
            email = (email or "").lower()
            if email and email not in data["suppressed"]:
                data["suppressed"].append(email)
            c = data["contacts"].get(email)
            if c and c["status"] in ("pending", "sent", "replied", "yes"):
                c["status"] = "no"
            self._save(data)

    def is_suppressed(self, email: str) -> bool:
        return (email or "").lower() in set(self._load()["suppressed"])

    def due(self, limit: int, groups: tuple[str, ...] = ("A", "B", "G")) -> list[Contact]:
        data = self._load()
        sup = set(data["suppressed"])
        pending = [Contact(**{k: v for k, v in c.items() if k in Contact.__dataclass_fields__}) for c in data["contacts"].values()
                   if c["status"] == "pending" and c["group"] in groups and c["email"] not in sup]
        pending.sort(key=lambda c: (c.group, c.name))
        return pending[:max(0, limit)]

    def expire_silent(self, now: float, wait_days: int) -> int:
        n = 0
        with file_lock(self.state.lock_path):
            data = self._load()
            for c in data["contacts"].values():
                if c["status"] == "sent" and now - float(c["sent_at"] or now) > wait_days * 86400:
                    c["status"] = "no_response"
                    n += 1
            self._save(data)
        return n

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self._load()["contacts"].values():
            out[c["status"]] = out.get(c["status"], 0) + 1
            out["group_" + c["group"]] = out.get("group_" + c["group"], 0) + 1
        out["suppressed"] = len(self._load()["suppressed"])
        return out


def given_name(full: str) -> str:
    parts = (full or "").split()
    return parts[-1] if parts else "bạn"
