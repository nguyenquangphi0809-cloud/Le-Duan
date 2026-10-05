"""Phiếu đề xuất (Word) cho khối lượng lớn ở ngách B: cơ quan dùng làm căn cứ xem xét hợp đồng.

Hệ thống chỉ soạn và gửi phiếu; ký hợp đồng, xuất hoá đơn là việc của chủ sở hữu (cơ quan nhà nước cần hợp đồng,
hoá đơn, nghiệm thu — không trả trước qua mã QR như khách cá nhân).
"""
from __future__ import annotations

from pathlib import Path

from .orders import PRICE_TEXT, SERVICES, quote_total
from .sample import make_docx


def _vnd(v: int) -> str:
    return f"{int(v):,}".replace(",", ".") + " đ"


def make_proposal(path: Path, customer: str, business: str, owner: str, contact_email: str, pages: int,
                  services: list[str], today: str, retention_days: int = 30) -> int:
    """Ghi phiếu đề xuất ra path, trả về dự toán (VND) theo đơn giá niêm yết."""
    estimate = quote_total(services, pages)
    paras = [
        "PHIẾU ĐỀ XUẤT DỊCH VỤ",
        f"Kính gửi: {customer or 'Quý cơ quan'}",
        f"Đơn vị cung cấp: {business}" + (f" — {owner} chịu trách nhiệm dịch vụ" if owner else ""),
        f"Liên hệ: {contact_email}",
        f"Ngày lập: {today}",
        "1. Nội dung công việc",
        *[f"- {SERVICES[s]['name']}: {PRICE_TEXT[s]}." for s in services if s in SERVICES],
        "2. Khối lượng và dự toán",
        f"- Khối lượng tài liệu ước tính: {pages} trang.",
        f"- Dự toán theo đơn giá niêm yết: {_vnd(estimate)}. Giá chốt theo khối lượng thực tế được nghiệm thu.",
        "3. Tiến độ",
        "- Chia thành các đợt 60–400 trang; mỗi đợt 3–5 ngày làm việc kể từ khi nhận đủ tài liệu của đợt.",
        "4. Sản phẩm bàn giao",
        "- Tệp Word Unicode của tài liệu được số hoá; bảng biên niên sự kiện hợp nhất (Excel và Word); bảng các chỗ nguồn ghi "
        "khác nhau; bảng mốc truyền thống của từng đơn vị cũ; báo cáo kiểm tra chất lượng của từng đợt.",
        "5. Bảo mật và giới hạn",
        "- Chỉ xử lý tài liệu không mật, đã công bố hoặc được cơ quan cho phép sử dụng; không xử lý hồ sơ cá nhân "
        "(hồ sơ đảng viên, lý lịch).",
        f"- Tài liệu được xử lý bằng dịch vụ AI của Anthropic (Hoa Kỳ) và được xoá sau tối đa {retention_days} ngày. "
        "Đơn vị không nhận lưu giữ tài liệu thay cơ quan.",
        "- Đơn vị không tự kết luận về sử liệu: chỗ các nguồn ghi khác nhau được liệt kê để người biên soạn và cấp ủy thẩm định.",
        "6. Hợp đồng và thanh toán",
        "- Hợp đồng dịch vụ theo khối lượng; thanh toán theo từng đợt nghiệm thu bằng chuyển khoản; có hoá đơn điện tử.",
    ]
    make_docx(Path(path), paras)
    return estimate
