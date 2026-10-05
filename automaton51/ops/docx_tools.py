"""Đọc .docx bằng thư viện chuẩn và KIỂM TRA CHẤT LƯỢNG TỰ ĐỘNG trước khi giao.

Chủ sở hữu không duyệt từng đơn, nên các phép kiểm tra khách quan này là lớp bảo vệ khách hàng:
  * tệp mở được, đúng định dạng;
  * không thêm nội dung mới đáng kể (định dạng / tài liệu tham khảo / hiệu đính không được viết thêm);
  * không làm mất nội dung của khách;
  * hiệu đính phải dùng Track Changes để khách tự duyệt từng chỗ;
  * tóm tắt tiếng Anh phải là tiếng Anh, độ dài hợp lý; luyện phản biện phải có slide và câu hỏi;
  * quyển tóm tắt luận án chỉ được rút từ chữ của luận án; trang đóng góp mới phải đủ hai thứ tiếng;
  * số hoá phải đủ trang; biên niên phải ghi nguồn kèm số trang cho từng sự kiện; chuyển phông không còn sót đoạn phông cũ;
  * phát hiện tài liệu mật / hồ sơ cá nhân thì dừng hẳn (không thử lại), báo khách và hoàn tiền.
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
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SOURCE_REF = re.compile(r"\btr\.?\s*\d|\btrang\s*\d|\bp{1,2}\.\s*\d", re.I)
STOP_FLAG = re.compile(r"PH[ÁA]T HI[ỆE]N (T[ÀA]I LI[ỆE]U M[ẬA]T|H[ỒO] S[ƠO] C[ÁA] NH[ÂA]N)", re.I)
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


def docx_text_from_bytes(data: bytes, limit: int = 20000) -> str:
    """Chữ của một tệp Word nằm trong bộ nhớ (tệp đính kèm thư), mỗi đoạn một dòng; lỗi thì trả chuỗi rỗng."""
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    xml = re.sub(r"</w:p>", "\n", xml[: limit * 20])
    text = re.sub(r"<[^>]+>", "", xml)
    from html import unescape
    return unescape(text)[:limit]


def read_text_any(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        s = read_docx(path)
        return s.accepted_text if s.ok else ""
    if path.suffix.lower() in (".md", ".txt"):
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def read_xlsx(path: Path) -> list[list[list[str]]]:
    """Đọc mọi trang tính (theo thứ tự sheet1, sheet2...) thành danh sách hàng, mỗi hàng là danh sách ô (chuỗi)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(X + "si"):
                    shared.append("".join(t.text or "" for t in si.iter(X + "t")))
            sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
            out: list[list[list[str]]] = []
            for n in sheets:
                rows = []
                for row in ET.fromstring(z.read(n)).iter(X + "row"):
                    cells = []
                    for c in row.iter(X + "c"):
                        kind, v = c.get("t"), c.find(X + "v")
                        if kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                            cells.append(shared[int(v.text)])
                        elif kind == "inlineStr":
                            cells.append("".join(t.text or "" for t in c.iter(X + "t")))
                        else:
                            cells.append(v.text if v is not None and v.text else "")
                    rows.append(cells)
                out.append(rows)
            return out
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        return []


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
    fatal: bool = False   # True: không thử lại (tài liệu mật, hồ sơ cá nhân)


# ngưỡng: (độ giữ tối thiểu, độ mới tối đa)
THRESHOLDS = {"DF": (0.90, 0.15), "TK": (0.85, 0.15), "HD": (0.80, 0.15), "BT": (0.85, 0.15)}


def _named(outputs: list[Path], prefix: str, exts: tuple[str, ...]) -> list[Path]:
    return [Path(p) for p in outputs if Path(p).name.upper().startswith(prefix) and Path(p).suffix.lower() in exts]


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def _diacritic_ratio(text: str) -> float:
    letters = re.findall(r"[^\W\d_]", text or "")
    return (sum(1 for c in letters if not c.isascii()) / len(letters)) if letters else 0.0


def bilingual_counts(text: str) -> tuple[int, int]:
    """(số chữ trong các đoạn tiếng Việt, số chữ trong các đoạn tiếng Anh) của một tệp song ngữ."""
    vi = en = 0
    for line in (text or "").splitlines():
        n = _word_count(line)
        if n < 4:
            continue
        if _diacritic_ratio(line) >= 0.08:
            vi += n
        elif looks_english(line)[0] or _diacritic_ratio(line) < 0.02:
            en += n
    return vi, en


def _check_new_services(res: "QAResult", services: list[str], inputs: list[Path], outputs: list[Path], report: str) -> None:
    from .legacy_fonts import docx_legacy_report
    from .orders import estimate_pages
    in_docx = [p for p in inputs if Path(p).suffix.lower() == ".docx"]
    if "TT" in services:
        outs = _named(outputs, "TOM_TAT_LUAN_AN", (".docx", ".md", ".txt"))
        if not outs:
            res.issues.append("thiếu tệp tóm tắt luận án")
        else:
            text = read_text_any(outs[0])
            n = _word_count(text)
            res.metrics["tt_words"] = n
            if n < 4000:
                res.issues.append(f"tóm tắt luận án quá ngắn ({n} chữ)")
            elif n > 16000:
                res.issues.append(f"tóm tắt luận án quá dài ({n} chữ)")
            if in_docx:
                src = read_text_any(in_docx[-1])
                _, nov = overlap(src, text)
                res.metrics["tt_novelty"] = round(nov, 3)
                if nov > 0.25:
                    res.issues.append(f"tóm tắt có nhiều chữ không có trong luận án ({nov:.0%}), có dấu hiệu viết thêm nội dung")
    if "TA" in services:
        outs = _named(outputs, "TOM_TAT_TIENG_ANH_LUAN_AN", (".docx", ".md", ".txt"))
        if not outs:
            res.issues.append("thiếu bản tiếng Anh của quyển tóm tắt")
        else:
            text = read_text_any(outs[0])
            eng, stats = looks_english(text)
            res.metrics.update({"ta_words": stats["ab_words"], "ta_diacritic_ratio": stats["ab_diacritic_ratio"]})
            if not eng and _diacritic_ratio(text) > 0.06:
                res.issues.append("bản tóm tắt tiếng Anh còn nhiều tiếng Việt")
            if stats["ab_words"] < 3000 and "cần bổ sung" not in (report or "").lower():
                res.issues.append("bản tóm tắt tiếng Anh quá ngắn")
    if "DG" in services:
        outs = _named(outputs, "THONG_TIN_DONG_GOP_MOI", (".docx", ".md", ".txt"))
        if not outs:
            res.issues.append("thiếu trang thông tin đóng góp mới")
        else:
            vi, en = bilingual_counts(read_text_any(outs[0]))
            res.metrics.update({"dg_vi_words": vi, "dg_en_words": en})
            if vi < 60:
                res.issues.append("trang đóng góp mới thiếu bản tiếng Việt")
            if en < 60:
                res.issues.append("trang đóng góp mới thiếu bản tiếng Anh")
    if "SH" in services:
        outs = _named(outputs, "SO_HOA", (".docx", ".md", ".txt"))
        expected = sum(estimate_pages(Path(p)) for p in inputs if Path(p).suffix.lower() not in (".docx", ".md", ".txt"))
        if not outs:
            res.issues.append("thiếu tệp số hoá")
        else:
            text = read_text_any(outs[0])
            marks = len(re.findall(r"\[Trang\s*\d+", text, re.I))
            res.metrics.update({"sh_pages_marked": marks, "sh_pages_expected": expected, "sh_words": _word_count(text)})
            if expected and marks < max(1, int(0.8 * expected)):
                res.issues.append(f"số hoá thiếu trang: có mốc {marks}/{expected} trang")
            if _word_count(text) < 15 * max(1, expected):
                res.issues.append("số hoá quá ít chữ so với số trang")
    if "NB" in services:
        outs = _named(outputs, "BIEN_NIEN", (".xlsx",))
        if not outs:
            res.issues.append("thiếu bảng biên niên (.xlsx)")
        else:
            sheets = read_xlsx(outs[0])
            rows = [r for r in (sheets[0][1:] if sheets else []) if any(c.strip() for c in r)]
            cited = [r for r in rows if any(SOURCE_REF.search(c or "") for c in r)]
            res.metrics.update({"nb_events": len(rows), "nb_cited": len(cited), "nb_sheets": len(sheets)})
            if len(sheets) < 2:
                res.issues.append("thiếu trang tính các chỗ nguồn ghi khác nhau")
            if len(rows) < 5:
                res.issues.append("biên niên quá ít sự kiện")
            elif len(cited) < 0.9 * len(rows):
                res.issues.append(f"nhiều sự kiện không ghi nguồn kèm số trang ({len(cited)}/{len(rows)})")
    if "BT" in services and not _named(outputs, "BANG_TRA_CUU", (".docx", ".md", ".xlsx")):
        res.issues.append("thiếu bảng tra cứu nhân danh, địa danh")
    if "CP" in services:
        outs = _named(outputs, "UNICODE_", (".docx", ".txt"))
        left = [p.name for p in outs if p.suffix.lower() == ".docx" and docx_legacy_report(p).changed]
        if left:
            res.issues.append("còn đoạn phông cũ chưa chuyển trong " + ", ".join(left))
        if not outs and "không phát hiện" not in (report or "").lower():
            res.issues.append("thiếu tệp đã chuyển phông")


def qa_check(services: list[str], inputs: list[Path], outputs: list[Path], report: str) -> QAResult:
    if STOP_FLAG.search(report or ""):
        return QAResult(False, ["phát hiện tài liệu mật hoặc hồ sơ cá nhân: dừng, không xử lý"], fatal=True)
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
        if "HD" in services or "BT" in services:
            total = max(1, sum(words(out_stats.original_text).values()))
            ratio = out_stats.inserted_words / total
            res.metrics.update({"insertions": out_stats.insertions, "deletions": out_stats.deletions,
                                "inserted_ratio": round(ratio, 3)})
            if "HD" in services and out_stats.insertions + out_stats.deletions == 0 and "không phát hiện" not in (report or "").lower():
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
    _check_new_services(res, services, inputs, outputs, report)
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
