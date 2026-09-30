"""Mẫu thư tự động. Mọi thư đều nói rõ do trợ lý AI soạn và gửi (không giả làm người)."""
from __future__ import annotations

from .orders import SERVICES


def footer(business: str, owner: str) -> str:
    return (f"\n\n--\n{business}" + (f" · {owner} chịu trách nhiệm dịch vụ" if owner else "") +
            "\nThư này do trợ lý AI của dịch vụ soạn và gửi tự động. Trả lời \"NGỪNG\" nếu bạn không muốn nhận thêm thư.")


def fmt_vnd(v: int) -> str:
    return f"{int(v):,}".replace(",", ".") + " đ"


def service_lines(services: list[str]) -> str:
    return "\n".join(f"  - {SERVICES[s]['name']}" for s in services if s in SERVICES)


def price_table() -> str:
    return (
        "  - Định dạng theo mẫu trường / Thông tư: 400.000–900.000 đ (theo số trang), 24 giờ\n"
        "  - Chuẩn hoá tài liệu tham khảo + đối chiếu trích dẫn: 300.000–800.000 đ, 24 giờ\n"
        "  - Hiệu đính ngôn ngữ học thuật (Track Changes): 25.000 đ/trang, tối thiểu 500.000 đ, 3 ngày\n"
        "  - Tóm tắt tiếng Anh + từ khoá + thư gửi tạp chí: 450.000 đ, 24 giờ\n"
        "  - Bộ câu hỏi luyện phản biện + slide bảo vệ: 900.000–1.500.000 đ, 3 ngày\n")


PRIVACY = ("Bản thảo được xử lý bằng dịch vụ AI của Anthropic (Hoa Kỳ) và được xoá khỏi hệ thống sau "
           "{days} ngày. Việc gửi bản thảo và thanh toán nghĩa là bạn đồng ý cách xử lý này.")

POLICY = ("Chúng tôi không viết hộ nội dung khoa học, không diễn đạt lại để \"hạ đạo văn\", không bịa tài liệu tham khảo. "
          "Mục nào không kiểm chứng được sẽ được đánh dấu để bạn tự bổ sung.")


def ask_details(name: str, business: str, owner: str) -> tuple[str, str]:
    subject = f"{business}: cần thêm thông tin để báo giá"
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã liên hệ. Để báo giá tự động, bạn trả lời thư này kèm:\n"
            "  1) Tệp bản thảo (Word .docx là tốt nhất, hoặc PDF)\n"
            "  2) Dịch vụ cần: định dạng / tài liệu tham khảo / hiệu đính / tóm tắt tiếng Anh / luyện phản biện\n"
            "  3) Mẫu trình bày hoặc kiểu trích dẫn trường/tạp chí yêu cầu (đính kèm nếu có)\n"
            "  4) Hạn nộp\n\nBảng giá:\n" + price_table() + "\n" + POLICY + footer(business, owner))
    return subject, body


def quote(order, business: str, owner: str, qr_url: str, bank_line: str, retention_days: int) -> tuple[str, str]:
    subject = f"[{order.code}] Báo giá: {fmt_vnd(order.price_vnd)}"
    hours = max((SERVICES[s]["hours"] for s in order.services if s in SERVICES), default=24)
    body = (f"Chào {order.customer_name or 'bạn'},\n\nBáo giá cho bản thảo khoảng {order.pages} trang:\n"
            f"{service_lines(order.services)}\n\nTổng: {fmt_vnd(order.price_vnd)}. Thời gian: trong {hours} giờ sau khi nhận thanh toán.\n\n"
            f"Thanh toán (quét mã QR, số tiền và nội dung đã điền sẵn):\n  {qr_url}\n"
            f"Hoặc chuyển khoản: {bank_line}\n  Số tiền: {fmt_vnd(order.price_vnd)}\n  Nội dung: {order.code}\n\n"
            f"Hệ thống tự nhận biết thanh toán khi nội dung có mã {order.code} và bắt đầu làm ngay. "
            f"Báo giá có hiệu lực 7 ngày. Bạn được sửa miễn phí 1 lần trong 14 ngày sau khi nhận bài.\n\n"
            + POLICY + "\n" + PRIVACY.format(days=retention_days) + footer(business, owner))
    return subject, body


def payment_received(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Đã nhận thanh toán, đang xử lý"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận {fmt_vnd(order.paid_vnd)} cho đơn {order.code}. "
            "Bản thảo đang được xử lý; kết quả sẽ gửi qua email này." + footer(business, owner))
    return subject, body


def partial_payment(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Thanh toán chưa đủ"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận {fmt_vnd(order.paid_vnd)} / {fmt_vnd(order.price_vnd)} cho đơn {order.code}. "
            f"Bạn chuyển thêm {fmt_vnd(order.price_vnd - order.paid_vnd)} với nội dung {order.code} để hệ thống bắt đầu xử lý."
            + footer(business, owner))
    return subject, body


def delivery(order, business: str, owner: str, report: str) -> tuple[str, str]:
    subject = f"[{order.code}] Đã hoàn thành"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nKết quả đơn {order.code} ở tệp đính kèm.\n\nBáo cáo thay đổi:\n{report.strip()[:6000]}\n\n"
            "Bạn kiểm tra và quyết định chấp nhận từng thay đổi. Cần chỉnh gì, trả lời thư này trong 14 ngày, "
            "ghi rõ yêu cầu: hệ thống sửa miễn phí 1 lần.\n\n" + POLICY + footer(business, owner))
    return subject, body


def declined(name: str, business: str, owner: str, reason: str) -> tuple[str, str]:
    subject = f"{business}: về yêu cầu của bạn"
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã liên hệ. Rất tiếc chúng tôi không nhận yêu cầu này"
            f"{(': ' + reason) if reason else ''}. Chúng tôi không viết hộ nội dung khoa học và không làm \"hạ đạo văn\".\n\n"
            "Chúng tôi có thể giúp bạn bằng các dịch vụ hợp lệ:\n" + price_table() +
            "\nNếu cần, bạn gửi bản thảo bạn đã viết để được báo giá." + footer(business, owner))
    return subject, body


def unsupported_revision(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Về yêu cầu chỉnh sửa"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐơn {order.code} đã dùng hết lượt sửa miễn phí hoặc đã quá 14 ngày. "
            "Bạn gửi thư mới kèm bản thảo và yêu cầu để được báo giá cho lần xử lý tiếp theo." + footer(business, owner))
    return subject, body


def escalated_customer(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Đã ghi nhận phản hồi của bạn"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã ghi nhận phản hồi về đơn {order.code}. Người phụ trách dịch vụ sẽ xem và phản hồi trong 48 giờ. "
            "Nếu đơn không thể hoàn thành đúng cam kết, bạn được hoàn tiền 100%." + footer(business, owner))
    return subject, body


def failed_customer(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Xin lỗi, đơn chưa hoàn thành được"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nHệ thống chưa xử lý được đơn {order.code} đạt chuẩn chất lượng. "
            f"Bạn sẽ được hoàn lại {fmt_vnd(order.paid_vnd)} vào tài khoản đã chuyển trong 48 giờ. Xin lỗi vì sự bất tiện."
            + footer(business, owner))
    return subject, body


def checklist(name: str, business: str, owner: str, checklist_text: str) -> tuple[str, str]:
    subject = "Checklist 20 lỗi trình bày trước khi nộp"
    body = (f"Chào {name or 'bạn'},\n\nChecklist bạn yêu cầu ở ngay bên dưới.\n\n{checklist_text.strip()}\n\n"
            "Nếu muốn nhận thông tin về dịch vụ hỗ trợ bản thảo, trả lời \"CÓ\"." + footer(business, owner))
    return subject, body


def services_info(name: str, business: str, owner: str) -> tuple[str, str]:
    subject = f"{business}: bảng giá và cách đặt"
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã đồng ý nhận thông tin. Bảng giá:\n" + price_table() +
            "\nCách đặt: gửi bản thảo vào thư này, hệ thống báo giá tự động kèm mã QR thanh toán.\n\n" + POLICY + footer(business, owner))
    return subject, body


def outreach_referrer(name: str, business: str, owner: str, owner_title: str, signup_hint: str) -> tuple[str, str]:
    subject = "Xin gửi anh/chị một tài liệu nhỏ cho học viên"
    body = (f"Kính gửi anh/chị {name},\n\n"
            "Thời gian qua tôi thấy nhiều học viên bị trả bài vì lỗi trình bày và trích dẫn hơn là vì nội dung. "
            "Tôi soạn checklist \"20 lỗi trình bày hay bị hội đồng bắt\", tặng miễn phí: " + signup_hint + "\n\n"
            "Nếu anh/chị thấy hữu ích, mong anh/chị chia sẻ cho học viên. Đoạn tin ngắn để dán vào nhóm lớp:\n"
            f"  \"Checklist 20 lỗi trình bày hay bị hội đồng bắt của {owner_title or owner}, tặng miễn phí: {signup_hint}\"\n\n"
            "Tôi cũng vừa mở dịch vụ hỗ trợ kỹ thuật cho bản thảo: định dạng, tài liệu tham khảo, hiệu đính, tóm tắt tiếng Anh, "
            "luyện phản biện. Dịch vụ do trợ lý AI thực hiện, có kiểm tra tự động, không viết hộ nội dung.\n\n"
            "Nếu anh/chị không muốn nhận thư như thế này, chỉ cần trả lời \"KHÔNG\", tôi sẽ không gửi nữa.\n\n"
            f"Trân trọng,\n{owner_title or owner}" + footer(business, owner))
    return subject, body


def outreach_learner(name: str, business: str, owner: str, owner_title: str, signup_hint: str) -> tuple[str, str]:
    subject = "Checklist 20 lỗi trình bày trước khi nộp"
    body = (f"Chào {name},\n\nMình vừa soạn checklist \"20 lỗi trình bày hay bị hội đồng bắt\", gửi {name} dùng thử trước khi nộp: "
            f"{signup_hint}\n\nMình có dịch vụ rà định dạng, tài liệu tham khảo và tóm tắt tiếng Anh, do trợ lý AI thực hiện, không viết hộ. "
            f"Nếu {name} muốn nhận thông tin về dịch vụ, trả lời \"CÓ\"; nếu không, cứ bỏ qua thư này, mình sẽ không gửi thêm.\n\n"
            f"{owner_title or owner}" + footer(business, owner))
    return subject, body
