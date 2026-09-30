"""Đọc .docx bằng thư viện chuẩn và KIỂM TRA CHẤT LƯỢNG TỰ ĐỘNG trước khi giao.

Chủ sở hữu không duyệt từng đơn, nên các phép kiểm tra khách quan này là lớp bảo vệ khách hàng:
  * tệp mở được, đúng định dạng;
  * không thêm nội dung mới đáng kể (định dạng / tài liệu tham khảo / hiệu đính không được viết thêm);
  * không làm mất nội dung của khách;
  * hiệu đính phải dùng Track Changes để khách tự duyệt từng chỗ;
  * tóm tắt tiếng Anh phải là tiếng Anh, độ dài hợp lý; luyện phản biện phải có slide và câu hỏi.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)


@dataclass
class DocxStats:
    ok: bool
    accepted_text: str = ""
    original_text: str = ""
    insertions: int = 0
    deletions: int = 0
    inserted_words: int = 0
    deleted_words: int = 0
    error: str = ""


def read_docx(path: Path) -> DocxStats:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        return DocxStats(ok=False, error=f"không đọc được tệp Word: {exc}")
    acc: list[str] = []
    orig: list[str] = []
    stats = DocxStats(ok=True)

    def walk(el, in_ins: bool, in_del: bool) -> None:
        tag = el.tag
        if tag == W + "ins":
            stats.insertions += 1
            in_ins = True
        elif tag == W + "del":
            stats.deletions += 1
            in_del = True
        if tag == W + "t" and el.text:
            acc.append(el.text)
            if not in_ins:
                orig.append(el.text)
            if in_ins:
                stats.inserted_words += len(WORD_RE.findall(el.text))
        elif tag == W + "delText" and el.text:
            orig.append(el.text)
            stats.deleted_words += len(WORD_RE.findall(el.text))
        elif tag == W + "p":
            acc.append("\n")
            orig.append("\n")
        for child in el:
            walk(child, in_ins, in_del)

    walk(root, False, False)
    stats.accepted_text = "".join(acc)
    stats.original_text = "".join(orig)
    return stats


def read_text_any(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        s = read_docx(path)
        return s.accepted_text if s.ok else ""
    if path.suffix.lower() in (".md", ".txt"):
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def words(text: str) -> Counter:
    return Counter(w.lower() for w in WORD_RE.findall(text or ""))


def overlap(original: str, new: str) -> tuple[float, float]:
    """(coverage, novelty): phần chữ của bản gốc còn giữ; phần chữ mới xuất hiện trong bản mới."""
    a, b = words(original), words(new)
    na, nb = sum(a.values()), sum(b.values())
    if na == 0 or nb == 0:
        return (0.0, 1.0)
    common = sum((a & b).values())
    return (common / na, (nb - common) / nb)


EN_STOP = {"the", "of", "and", "in", "to", "a", "is", "this", "that", "for", "on", "with", "as", "by", "are", "study", "from"}


def looks_english(text: str) -> tuple[bool, dict]:
    """Tiếng Việt cũng viết bằng chữ Latin nên không thể chỉ đếm ký tự ASCII: dùng tỷ lệ chữ có dấu (tiếng Anh gần 0)
    và tỷ lệ từ chức năng tiếng Anh."""
    letters = re.findall(r"[^\W\d_]", text or "")
    toks = re.findall(r"[A-Za-z]+", (text or "").lower())
    non_ascii = (sum(1 for c in letters if not c.isascii()) / len(letters)) if letters else 1.0
    stop = (sum(1 for t in toks if t in EN_STOP) / len(toks)) if toks else 0.0
    n = len((text or "").split())
    return (non_ascii < 0.04 and stop >= 0.08), {"ab_words": n, "ab_diacritic_ratio": round(non_ascii, 3), "ab_en_stopword_ratio": round(stop, 3)}


def is_zip_with(path: Path, member_prefix: str) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.startswith(member_prefix) for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


@dataclass
class QAResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ngưỡng: (độ giữ tối thiểu, độ mới tối đa)
THRESHOLDS = {"DF": (0.90, 0.15), "TK": (0.85, 0.15), "HD": (0.80, 0.15)}


def qa_check(services: list[str], inputs: list[Path], outputs: list[Path], report: str) -> QAResult:
    res = QAResult(passed=True)
    in_docx = [p for p in inputs if Path(p).suffix.lower() == ".docx"]
    out_docx = [p for p in outputs if Path(p).suffix.lower() == ".docx"]
    edit_services = [s for s in services if s in THRESHOLDS]

    if edit_services:
        main_out = _pick_main(out_docx)
        if main_out is None:
            return QAResult(False, ["thiếu tệp Word kết quả"])
        out_stats = read_docx(main_out)
        if not out_stats.ok:
            return QAResult(False, [out_stats.error])
        if in_docx:
            src = read_docx(in_docx[-1])
            src_text = src.accepted_text if src.ok else ""
            cov, nov = overlap(src_text, out_stats.accepted_text)
            min_cov = min(THRESHOLDS[s][0] for s in edit_services)
            max_nov = max(THRESHOLDS[s][1] for s in edit_services)
            res.metrics.update({"coverage": round(cov, 3), "novelty": round(nov, 3)})
            if cov < min_cov:
                res.issues.append(f"bản kết quả làm mất nội dung của khách (giữ {cov:.0%} < {min_cov:.0%})")
            if nov > max_nov:
                res.issues.append(f"bản kết quả thêm quá nhiều chữ mới ({nov:.0%} > {max_nov:.0%}), có dấu hiệu viết thêm nội dung")
        if "HD" in services:
            total = max(1, sum(words(out_stats.original_text).values()))
            ratio = out_stats.inserted_words / total
            res.metrics.update({"insertions": out_stats.insertions, "deletions": out_stats.deletions,
                                "inserted_ratio": round(ratio, 3)})
            if out_stats.insertions + out_stats.deletions == 0 and "không phát hiện" not in (report or "").lower():
                res.issues.append("hiệu đính không có Track Changes để khách duyệt")
            if ratio > 0.15:
                res.issues.append(f"hiệu đính chèn quá nhiều chữ ({ratio:.0%}), có dấu hiệu viết thêm nội dung")
    if "AB" in services:
        texts = [read_text_any(p) for p in outputs if Path(p).suffix.lower() in (".docx", ".md", ".txt")]
        text = max(texts, key=len) if texts else ""
        eng, stats = looks_english(text)
        res.metrics.update(stats)
        if stats["ab_words"] < 80:
            res.issues.append("tóm tắt tiếng Anh quá ngắn hoặc thiếu")
        if not eng:
            res.issues.append("tóm tắt không phải tiếng Anh")
    if "PB" in services:
        if not any(Path(p).suffix.lower() == ".pptx" and is_zip_with(Path(p), "ppt/") for p in outputs):
            res.issues.append("thiếu slide bảo vệ (.pptx)")
        qtexts = [read_text_any(p) for p in outputs if Path(p).suffix.lower() in (".docx", ".md", ".txt")]
        if not any(t.count("?") >= 20 for t in qtexts):
            res.issues.append("bộ câu hỏi phản biện có ít hơn 20 câu")
    if not (report or "").strip():
        res.issues.append("thiếu báo cáo thay đổi cho khách")
    res.passed = not res.issues
    return res


def _pick_main(docx: list[Path]) -> Optional[Path]:
    if not docx:
        return None
    for p in docx:
        if Path(p).name.upper().startswith("KET_QUA"):
            return p
    return max(docx, key=lambda p: Path(p).stat().st_size)
