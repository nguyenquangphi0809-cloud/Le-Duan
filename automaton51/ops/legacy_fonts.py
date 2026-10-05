"""Chuyển văn bản gõ bằng phông cũ TCVN3 (.VnTime, ABC) và VNI-Windows (VNI-Times) sang Unicode, chạy tại máy.

Tài liệu cơ quan, nhà trường giai đoạn 1993–2010 phần lớn gõ bằng hai bảng mã này: mở trên máy
không có phông cũ sẽ thành "Hµ Néi", "Vieät Nam". Chuyển bằng bảng mã cố định nên chính xác,
không tốn tiền gọi AI, và tài liệu không phải rời khỏi máy.

Quyết định theo từng ĐOẠN (w:p): Word hay cắt một từ thành nhiều run ("Hµ N" + "éi").
Đoạn đã có chữ Việt Unicode dựng sẵn (ạ, ố, ư, đ...) thì giữ nguyên. Chỉ chuyển khi bản chuyển
"đúng tiếng Việt" hơn bản gốc (ít âm tiết sai hơn), nên văn bản Unicode không bao giờ bị làm hỏng.
"""
from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from xml.sax.saxutils import escape

# ---------------------------------------------------------------- TCVN3 (TCVN 5712:1993, bộ phông .Vn*)
_TCVN3_PAIRS = (
    "¡Ă ¢Â £Ê ¤Ô ¥Ơ ¦Ư §Đ ¨ă ©â ªê «ô ¬ơ ­ư ®đ "
    "µà ¸á ¶ả ·ã ¹ạ »ằ ¾ắ ¼ẳ ½ẵ Æặ Çầ Êấ Èẩ Éẫ Ëậ "
    "Ìè Ðé Îẻ Ïẽ Ñẹ Òề Õế Óể Ôễ Öệ ×ì Ýí Øỉ Üĩ Þị "
    "ßò ãó áỏ âõ äọ åồ èố æổ çỗ éộ êờ íớ ëở ìỡ îợ "
    "ïù óú ñủ òũ ôụ õừ øứ öử ÷ữ ùự úỳ ýý ûỷ üỹ þỵ"
)
TCVN3 = {pair[0]: pair[1] for pair in _TCVN3_PAIRS.split()}
# Ký tự chỉ có trong văn bản TCVN3: không bao giờ xuất hiện trong văn bản VNI hay tiếng Việt Unicode
TCVN3_ONLY = set("¡¢£¤¥¦§¨©ª«¬­®µ¸¶·¹»¾¼½Ç×Þßç÷þ")
# Chữ thường đứng ngay trước một "chữ hoa" Latin-1 (ViÖt, kÕt, lËp): TCVN3 dùng các mã này cho nguyên âm thường có dấu;
# VNI không bao giờ sinh ra cặp này (dấu của chữ thường là ký tự thường).
TCVN3_PAIR = re.compile("[a-z\u00e0-\u00ff][\u00c0-\u00de]")

# ---------------------------------------------------------------- VNI-Windows (bộ phông VNI-*)
_GRAVE, _ACUTE, _HOOK, _TILDE, _DOT = "̀", "́", "̉", "̃", "̣"
VNI_TONE = {"ø": _GRAVE, "ù": _ACUTE, "û": _HOOK, "õ": _TILDE, "ï": _DOT,
            "Ø": _GRAVE, "Ù": _ACUTE, "Û": _HOOK, "Õ": _TILDE, "Ï": _DOT}
VNI_HAT = {"â": "", "à": _GRAVE, "á": _ACUTE, "å": _HOOK, "ã": _TILDE, "ä": _DOT,
           "Â": "", "À": _GRAVE, "Á": _ACUTE, "Å": _HOOK, "Ã": _TILDE, "Ä": _DOT}       # sau a/e/o: â ê ô
VNI_BREVE = {"ê": "", "è": _GRAVE, "é": _ACUTE, "ú": _HOOK, "ü": _TILDE, "ë": _DOT,
             "Ê": "", "È": _GRAVE, "É": _ACUTE, "Ú": _HOOK, "Ü": _TILDE, "Ë": _DOT}     # sau a: ă
VNI_SINGLE = {"ñ": "đ", "Ñ": "Đ", "ô": "ơ", "Ô": "Ơ", "ö": "ư", "Ö": "Ư",
              "æ": "ỉ", "ó": "ĩ", "ò": "ị", "î": "ỵ", "Æ": "Ỉ", "Ó": "Ĩ", "Ò": "Ị", "Î": "Ỵ"}
VNI_PATTERN = re.compile(r"[aeouyAEOUY][øùûõïØÙÛÕÏ]|[aeoAEO][âàáåãäÂÀÁÅÃÄ]|[aA][êèéúüëÊÈÉÚÜË]|[ôÔöÖ][øùûõïØÙÛÕÏ]|\b[ñÑ]")

# Chữ Việt Unicode dựng sẵn mà TCVN3/VNI không bao giờ sinh ra (â ê ô bị loại vì cả hai bảng mã cũ đều dùng)
VIET_UNICODE = re.compile("[Ạ-ỹĂăĐđƠơƯưĨĩŨũ]")
TONES = {_GRAVE, _ACUTE, _HOOK, _TILDE, _DOT}
SHAPES = {"̂", "̆", "̛"}  # mũ, trăng, móc
VOWELS = set("aeiouyAEIOUY")
TOKEN = re.compile(r"[^\s\d.,;:!?()\[\]{}\"'“”‘’/\\\-–—…%+=<>*#@&_|]+")


def _compose(base: str, mark: str) -> str:
    return unicodedata.normalize("NFC", base + mark) if mark else base


def tcvn3_to_unicode(text: str, upper: bool = False) -> str:
    out = "".join(TCVN3.get(ch, ch) for ch in text)
    return out.upper() if upper else out


def vni_to_unicode(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch, nxt = text[i], (text[i + 1] if i + 1 < n else "")
        low = ch.lower()
        if low in ("a", "e", "o") and nxt in VNI_HAT:
            base = {"a": "â", "e": "ê", "o": "ô"}[low]
            out.append(_compose(base.upper() if ch.isupper() else base, VNI_HAT[nxt]))
            i += 2
        elif low == "a" and nxt in VNI_BREVE:
            out.append(_compose("Ă" if ch.isupper() else "ă", VNI_BREVE[nxt]))
            i += 2
        elif ch in "ôÔöÖ" and nxt in VNI_TONE:
            out.append(_compose(VNI_SINGLE[ch], VNI_TONE[nxt]))
            i += 2
        elif ch in VOWELS and nxt in VNI_TONE:
            out.append(_compose(ch, VNI_TONE[nxt]))
            i += 2
        else:
            out.append(VNI_SINGLE.get(ch, ch))
            i += 1
    return "".join(out)


def _char_ok(ch: str) -> bool:
    if ch.isascii() or ch in "đĐ":
        return True
    d = unicodedata.normalize("NFD", ch)
    marks = d[1:]
    return (d[0] in VOWELS and all(m in TONES or m in SHAPES for m in marks)
            and sum(m in TONES for m in marks) <= 1)


def bad_syllables(text: str) -> int:
    """Số "từ" không thể là tiếng Việt: có ký tự lạ (µ, ø, ¸...) hoặc mang từ hai dấu thanh trở lên."""
    bad = 0
    for tok in TOKEN.findall(text or ""):
        if not all(_char_ok(c) for c in tok):
            bad += 1
            continue
        tones = sum(1 for c in tok for m in unicodedata.normalize("NFD", c)[1:] if m in TONES)
        if tones > 1:
            bad += 1
    return bad


def detect(text: str, hint: str = "") -> str:
    """'unicode' | 'tcvn3' | 'vni' | 'ascii'. hint: bảng mã suy ra từ tên phông (nếu có)."""
    text = text or ""
    if VIET_UNICODE.search(text):
        return "unicode"
    t = sum(1 for ch in text if ch in TCVN3_ONLY) + len(TCVN3_PAIR.findall(text))
    v = len(VNI_PATTERN.findall(text))
    if hint in ("tcvn3", "vni"):
        return hint
    if max(t, v) < 1:
        return "ascii"
    return "tcvn3" if t >= v else "vni"


def convert_text(text: str, encoding: str = "", upper: bool = False) -> str:
    enc = encoding or detect(text)
    if enc == "tcvn3":
        return tcvn3_to_unicode(text, upper)
    if enc == "vni":
        out = vni_to_unicode(text)
        return out.upper() if upper else out
    return text


def convert_plain(text: str) -> tuple[str, str]:
    """Chuyển một văn bản thuần (txt). Trả (văn bản mới, bảng mã đã dùng hoặc '').
    Cả văn bản cùng một bảng mã cũ (thường gặp) thì chuyển mọi dòng theo bảng mã đó, kể cả dòng ngắn như dấu "MËT";
    văn bản lẫn Unicode thì xét từng dòng."""
    whole = detect(text)
    if whole in ("tcvn3", "vni"):
        out_lines = [p if VIET_UNICODE.search(p) else convert_text(p, whole) for p in text.split("\n")]
        joined = "\n".join(out_lines)
        if bad_syllables(joined) < bad_syllables(text):
            return joined, whole
    paras = text.split("\n")
    out, used = [], ""
    for p in paras:
        enc = detect(p)
        if enc in ("tcvn3", "vni"):
            q = convert_text(p, enc)
            if bad_syllables(q) < bad_syllables(p):
                out.append(q)
                used = used or enc
                continue
        out.append(p)
    return "\n".join(out), used


# ---------------------------------------------------------------- .docx
_TAG = re.compile(r"<(/?)w:(p|r|t|rFonts)\b([^>]*?)(/?)>")
_FONT_ATTR = re.compile(r'w:(ascii|hAnsi|cs|eastAsia)="([^"]*)"')


@dataclass
class ConversionReport:
    paragraphs_converted: int = 0
    tcvn3: int = 0
    vni: int = 0
    fonts_seen: set = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return self.paragraphs_converted > 0

    def add(self, other: "ConversionReport") -> None:
        self.paragraphs_converted += other.paragraphs_converted
        self.tcvn3 += other.tcvn3
        self.vni += other.vni
        self.fonts_seen |= other.fonts_seen


def font_encoding(font: str) -> str:
    f = (font or "").strip().lower()
    if f.startswith(".vn"):
        return "tcvn3"
    if f.startswith("vni"):
        return "vni"
    return ""


def _upper_font(font: str) -> bool:
    f = (font or "").strip().lower()
    return f.startswith(".vn") and f.endswith("h")


def convert_document_xml(xml: str, new_font: str = "Times New Roman") -> tuple[str, ConversionReport]:
    """Chuyển các đoạn gõ bằng TCVN3/VNI trong một phần XML của Word sang Unicode, đổi phông cũ sang phông Unicode."""
    report = ConversionReport()
    tokens = list(_TAG.finditer(xml))
    texts: dict[int, list[str]] = {}
    fonts: dict[int, set] = {}
    owner: dict[int, tuple[int, str]] = {}  # vị trí nội dung w:t -> (đoạn, phông của run)
    stack: list[int] = []
    count, font, open_at = 0, "", -1
    for m in tokens:
        closing, name, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if name == "p":
            if not closing and not selfclose:
                count += 1
                stack.append(count)
                texts[count], fonts[count] = [], set()
            elif closing and stack:
                stack.pop()
        elif name == "r" and not closing:
            font = ""
        elif name == "rFonts" and not closing:
            found = dict(_FONT_ATTR.findall(attrs))
            font = found.get("ascii") or found.get("hAnsi") or ""
            if font:
                report.fonts_seen.add(font)
                if stack:
                    fonts[stack[-1]].add(font)
        elif name == "t" and not closing and not selfclose:
            open_at = m.end()
        elif name == "t" and closing and open_at >= 0:
            if stack:
                texts[stack[-1]].append(unescape(xml[open_at:m.start()]))
                owner[open_at] = (stack[-1], font)
            open_at = -1
    decision: dict[int, str] = {}
    for pid, parts in texts.items():
        raw = "".join(parts)
        hints = {font_encoding(f) for f in fonts[pid]} - {""}
        enc = detect(raw, hints.pop() if len(hints) == 1 else "")
        if enc not in ("tcvn3", "vni"):
            continue
        if bad_syllables(convert_text(raw, enc)) > bad_syllables(raw):
            continue  # chuyển làm văn bản "kém tiếng Việt" hơn: giữ nguyên
        decision[pid] = enc
        report.paragraphs_converted += 1
        if enc == "tcvn3":
            report.tcvn3 += 1
        else:
            report.vni += 1
    if not decision:
        return xml, report
    out: list[str] = []
    last = 0
    for start, (pid, run_font) in sorted(owner.items()):
        if pid not in decision:
            continue
        end = xml.find("</w:t>", start)
        enc = font_encoding(run_font) or decision[pid]
        out.append(xml[last:start])
        out.append(escape(convert_text(unescape(xml[start:end]), enc, upper=_upper_font(run_font))))
        last = end
    out.append(xml[last:])
    converted = "".join(out)

    def swap(fm: re.Match) -> str:
        return f'w:{fm.group(1)}="{new_font}"' if font_encoding(fm.group(2)) else fm.group(0)
    converted = re.sub(r"<w:rFonts\b[^>]*>", lambda m: _FONT_ATTR.sub(swap, m.group(0)), converted)
    return converted, report


_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def convert_docx(src: Path, dst: Path, new_font: str = "Times New Roman") -> ConversionReport:
    """Ghi bản Unicode của src ra dst: thân văn bản, đầu/chân trang, chú thích; đổi phông cũ trong styles.xml."""
    src, dst = Path(src), Path(dst)
    total = ConversionReport()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if _PARTS.match(item.filename):
                    xml, rep = convert_document_xml(data.decode("utf-8"), new_font)
                    total.add(rep)
                    data = xml.encode("utf-8")
                elif item.filename == "word/styles.xml":
                    styles = re.sub(r'(w:(?:ascii|hAnsi|cs|eastAsia)=")((?:\.vn|vni)[^"]*)(")',
                                    lambda m: m.group(1) + new_font + m.group(3), data.decode("utf-8"), flags=re.I)
                    data = styles.encode("utf-8")
                zout.writestr(item, data)
        tmp.replace(dst)
    finally:
        if tmp.exists():
            tmp.unlink()
    return total


def docx_legacy_report(path: Path) -> ConversionReport:
    """Đo (không ghi) xem tệp Word có bao nhiêu đoạn gõ bằng phông cũ."""
    total = ConversionReport()
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if _PARTS.match(name):
                    total.add(convert_document_xml(z.read(name).decode("utf-8", errors="ignore"))[1])
    except (zipfile.BadZipFile, OSError):
        pass
    return total
