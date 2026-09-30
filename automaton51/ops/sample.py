"""Tạo tệp .docx tối thiểu hợp lệ (thư viện chuẩn) cho chạy thử và test."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
      '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>')
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path: Path, paragraphs: list[str], pages: int = 0, tracked: list[tuple[str, str]] | None = None) -> Path:
    """tracked: danh sách (chữ bị xoá, chữ được chèn) thêm vào cuối dưới dạng Track Changes."""
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    for i, (old, new) in enumerate(tracked or []):
        body += (f"<w:p><w:del w:id=\"{2 * i}\" w:author=\"Trợ lý biên tập\"><w:r><w:delText>{escape(old)}</w:delText></w:r></w:del>"
                 f"<w:ins w:id=\"{2 * i + 1}\" w:author=\"Trợ lý biên tập\"><w:r><w:t>{escape(new)}</w:t></w:r></w:ins></w:p>")
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{body}</w:body></w:document>'
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           f'<Pages>{int(pages)}</Pages></Properties>')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/app.xml", app)
    return path


def sample_thesis_paragraphs(n: int = 40) -> list[str]:
    base = ("Chương {i}. Luận văn phân tích vai trò của nguồn tư liệu lưu trữ trong nghiên cứu lịch sử địa phương, "
            "đối chiếu các văn bản gốc với hồi ký và báo chí đương thời để xác định độ tin cậy của từng nguồn.")
    return [base.format(i=i) for i in range(1, n + 1)]
