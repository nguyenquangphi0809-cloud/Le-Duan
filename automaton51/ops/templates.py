"""Mẫu thư tự động. Mọi thư đều nói rõ do trợ lý AI soạn và gửi (không giả làm người).

Thư quảng cáo (gửi danh bạ, gửi bảng giá cho người đã đồng ý) theo Nghị định 91/2020: tiêu đề bắt đầu bằng [QC],
có thông tin người gửi và cách từ chối nhận thư. Thư giao dịch (báo giá, giao hàng, trả lời câu hỏi) không phải quảng cáo.
"""
from __future__ import annotations

from .orders import BUNDLE_TEXT, BUNDLES, LINES, PRICE_TEXT, SERVICES, bundles_in, hours_text

QC = "[QC] "


def footer(business: str, owner: str) -> str:
    return (f"\n\n--\n{business}" + (f" · {owner} chịu trách nhiệm dịch vụ" if owner else "") +
            "\nThư này do trợ lý AI của dịch vụ soạn và gửi tự động. Trả lời \"NGỪNG\" nếu bạn không muốn nhận thêm thư.")


def marketing_footer(business: str, owner: str, sender: str) -> str:
    """Chân thư quảng cáo: thông tin người gửi ngay trước dòng từ chối nhận thư."""
    return (f"\n\n--\n{business}" + (f" · {owner} chịu trách nhiệm dịch vụ" if owner else "") +
            (f"\n{sender}" if sender else "") +
            "\nThư này do trợ lý AI của dịch vụ soạn và gửi tự động."
            "\nKhông muốn nhận thư giới thiệu dịch vụ nữa: trả lời \"NGỪNG\" (hệ thống dừng gửi ngay).")


def fmt_vnd(v: int) -> str:
    return f"{int(v):,}".replace(",", ".") + " đ"


def service_lines(services: list[str]) -> str:
    return "\n".join(f"  - {SERVICES[s]['name']}" for s in services if s in SERVICES)


def price_table(line: str = "") -> str:
    """Bảng giá sinh từ mã (cùng nguồn với cách tính giá), theo ngách A, B hoặc cả hai."""
    parts = []
    for ln in (line,) if line in LINES else tuple(LINES):
        rows = [f"  - {SERVICES[c]['name']}: {PRICE_TEXT[c]}, {hours_text(SERVICES[c]['hours'])}"
                for c in SERVICES if SERVICES[c]["line"] == ln]
        rows += [f"  - {BUNDLES[b]['name']}: {BUNDLE_TEXT[b]}" for b in BUNDLES if BUNDLES[b]["line"] == ln]
        parts.append(("" if line else f" {LINES[ln]}:\n") + "\n".join(rows))
    return "\n".join(parts) + "\n"


PRIVACY = ("Bản thảo được xử lý bằng dịch vụ AI của Anthropic (Hoa Kỳ) và được xoá khỏi hệ thống sau "
           "{days} ngày. Việc gửi bản thảo và thanh toán nghĩa là bạn đồng ý cách xử lý này.")

POLICY = ("Chúng tôi không viết hộ nội dung khoa học, không diễn đạt lại để \"hạ đạo văn\", không bịa tài liệu tham khảo. "
          "Mục nào không kiểm chứng được sẽ được đánh dấu để bạn tự bổ sung.")

POLICY_B = ("Chỉ nhận tài liệu KHÔNG MẬT, đã công bố hoặc được cơ quan cho phép xử lý; không nhận hồ sơ cá nhân "
            "(hồ sơ đảng viên, lý lịch). Chúng tôi không tự kết luận về sử liệu: chỗ các nguồn ghi khác nhau được liệt kê "
            "để người biên soạn thẩm định. Không lưu giữ tài liệu thay cơ quan.")


def ask_details(name: str, business: str, owner: str, line: str = "") -> tuple[str, str]:
    subject = f"{business}: cần thêm thông tin để báo giá"
    if line == "B":
        need = ("  1) Tệp tài liệu: Word .docx (chuyển phông, biên tập), PDF hoặc ảnh chụp (số hoá)\n"
                "  2) Việc cần làm: chuyển phông / số hoá / biên niên hợp nhất / biên tập bản thảo\n"
                "  3) Các đơn vị cũ liên quan (nếu là hợp nhất sử liệu xã mới) và thời hạn\n")
    else:
        need = ("  1) Tệp bản thảo (Word .docx là tốt nhất, hoặc PDF)\n"
                "  2) Dịch vụ cần: định dạng / tài liệu tham khảo / hiệu đính / tóm tắt / luyện phản biện / gói trọn bộ\n"
                "  3) Mẫu trình bày hoặc kiểu trích dẫn trường/tạp chí yêu cầu (đính kèm nếu có)\n"
                "  4) Hạn nộp\n")
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã liên hệ. Để báo giá tự động, bạn trả lời thư này kèm:\n" + need +
            "\nBảng giá:\n" + price_table(line) + "\n" + (POLICY_B if line == "B" else POLICY) + footer(business, owner))
    return subject, body


def need_format(name: str, business: str, owner: str, missing: list[tuple[str, tuple]]) -> tuple[str, str]:
    exts = sorted({e for _, accepts in missing for e in accepts})
    word = ".docx" in exts and len(exts) <= 2
    subject = f"{business}: cần tệp Word (.docx)" if word else f"{business}: cần tệp đúng định dạng"
    lines = "\n".join(f"  - {SERVICES[s]['name']}: {', '.join(a)}" for s, a in missing)
    body = (f"Chào {name},\n\nĐể xử lý tự động, mỗi dịch vụ cần tệp đúng định dạng:\n{lines}\n\n"
            "Tệp .doc đời cũ: mở bằng Word rồi chọn Lưu thành .docx (kể cả tệp gõ phông .VnTime). "
            "Bạn gửi lại tệp phù hợp để nhận báo giá.\n\nBảng giá:\n" + price_table() + footer(business, owner))
    return subject, body


def quote(order, business: str, owner: str, qr_url: str, bank_line: str, retention_days: int) -> tuple[str, str]:
    subject = f"[{order.code}] Báo giá: {fmt_vnd(order.price_vnd)}"
    hours = max((SERVICES[s]["hours"] for s in order.services if s in SERVICES), default=24)
    deals = bundles_in(order.services)
    deal_line = ("\n" + "\n".join(f"Đã áp dụng {BUNDLES[b]['name']}: {BUNDLE_TEXT[b].split(' (')[0]}." for b in deals)) if deals else ""
    is_b = any(SERVICES.get(s, {}).get("line") == "B" for s in order.services)
    body = (f"Chào {order.customer_name or 'bạn'},\n\nBáo giá cho tài liệu khoảng {order.pages} trang:\n"
            f"{service_lines(order.services)}\n\nTổng: {fmt_vnd(order.price_vnd)}.{deal_line}\n"
            f"Thời gian: trong {hours_text(hours)} sau khi nhận thanh toán.\n\n"
            f"Thanh toán (quét mã QR, số tiền và nội dung đã điền sẵn):\n  {qr_url}\n"
            f"Hoặc chuyển khoản: {bank_line}\n  Số tiền: {fmt_vnd(order.price_vnd)}\n  Nội dung: {order.code}\n\n"
            f"Hệ thống tự nhận biết thanh toán khi nội dung có mã {order.code} và bắt đầu làm ngay. "
            f"Báo giá có hiệu lực 7 ngày. Bạn được sửa miễn phí 1 lần trong 14 ngày sau khi nhận bài.\n\n"
            + (POLICY_B + "\n" if is_b else "") + POLICY + "\n" + PRIVACY.format(days=retention_days) + footer(business, owner))
    return subject, body


def payment_received(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Đã nhận thanh toán, đang xử lý"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận {fmt_vnd(order.paid_vnd)} cho đơn {order.code}. "
            "Bản thảo đang được xử lý; kết quả sẽ gửi qua email này." + footer(business, owner))
    return subject, body


def free_accepted(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Đã nhận tệp, đang chuyển phông (miễn phí)"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận tệp của bạn. Hệ thống đang chuyển phông TCVN3/VNI sang Unicode "
            "ngay trên máy chủ của dịch vụ (không gửi cho bên thứ ba, không dùng AI) và sẽ gửi lại qua email này trong ít phút. "
            "Dịch vụ miễn phí cho tệp tới 50 trang." + footer(business, owner))
    return subject, body


def partial_payment(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Thanh toán chưa đủ"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nĐã nhận {fmt_vnd(order.paid_vnd)} / {fmt_vnd(order.price_vnd)} cho đơn {order.code}. "
            f"Bạn chuyển thêm {fmt_vnd(order.price_vnd - order.paid_vnd)} với nội dung {order.code} để hệ thống bắt đầu xử lý."
            + footer(business, owner))
    return subject, body


def delivery(order, business: str, owner: str, report: str, extra: str = "") -> tuple[str, str]:
    subject = f"[{order.code}] Đã hoàn thành"
    policy = POLICY_B if any(SERVICES.get(s, {}).get("line") == "B" for s in order.services) else POLICY
    body = (f"Chào {order.customer_name or 'bạn'},\n\nKết quả đơn {order.code} ở tệp đính kèm.\n\nBáo cáo thay đổi:\n{report.strip()[:6000]}\n\n"
            "Bạn kiểm tra và quyết định chấp nhận từng thay đổi. Cần chỉnh gì, trả lời thư này trong 14 ngày, "
            "ghi rõ yêu cầu: hệ thống sửa miễn phí 1 lần.\n\n" + (extra.strip() + "\n\n" if extra else "") + policy + footer(business, owner))
    return subject, body


def declined(name: str, business: str, owner: str, reason: str) -> tuple[str, str]:
    subject = f"{business}: về yêu cầu của bạn"
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã liên hệ. Rất tiếc chúng tôi không nhận yêu cầu này"
            f"{(': ' + reason) if reason else ''}. Chúng tôi không viết hộ nội dung khoa học và không làm \"hạ đạo văn\".\n\n"
            "Chúng tôi có thể giúp bạn bằng các dịch vụ hợp lệ:\n" + price_table() +
            "\nNếu cần, bạn gửi bản thảo bạn đã viết để được báo giá." + footer(business, owner))
    return subject, body


def restricted(name: str, business: str, owner: str) -> tuple[str, str]:
    subject = f"{business}: không thể nhận tài liệu này"
    body = (f"Chào {name or 'bạn'},\n\nTài liệu bạn gửi có dấu hiệu là tài liệu mật hoặc hồ sơ cá nhân (hồ sơ đảng viên, lý lịch...). "
            "Theo quy định về bảo vệ bí mật nhà nước và bảo vệ dữ liệu cá nhân, dịch vụ không tiếp nhận và không xử lý loại tài "
            "liệu này; hệ thống không lưu tệp. Đề nghị bạn KHÔNG gửi tài liệu mật qua email hay mạng xã hội.\n\n"
            "Nếu đây là tài liệu đã công bố hoặc đã được cơ quan cho phép sử dụng công khai, bạn gửi lại kèm một dòng xác nhận "
            "\"Tài liệu không mật, đã được phép sử dụng\" và bỏ phần thông tin cá nhân (nếu có)." + footer(business, owner))
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
    refund = (f"Bạn sẽ được hoàn lại {fmt_vnd(order.paid_vnd)} vào tài khoản đã chuyển trong 48 giờ. " if order.paid_vnd else "")
    body = (f"Chào {order.customer_name or 'bạn'},\n\nHệ thống chưa xử lý được đơn {order.code} đạt chuẩn chất lượng. "
            + refund + "Xin lỗi vì sự bất tiện." + footer(business, owner))
    return subject, body


def stopped_customer(order, business: str, owner: str) -> tuple[str, str]:
    subject = f"[{order.code}] Dừng xử lý: phát hiện tài liệu mật hoặc hồ sơ cá nhân"
    body = (f"Chào {order.customer_name or 'bạn'},\n\nKhi xử lý đơn {order.code}, hệ thống phát hiện trong tệp có dấu chỉ độ mật hoặc "
            "hồ sơ cá nhân nên đã DỪNG, không xử lý tiếp và sẽ xoá tệp. "
            + (f"Bạn sẽ được hoàn lại {fmt_vnd(order.paid_vnd)} trong 48 giờ. " if order.paid_vnd else "")
            + "Đề nghị không gửi tài liệu mật qua email hay mạng xã hội." + footer(business, owner))
    return subject, body


def checklist(name: str, business: str, owner: str, checklist_text: str) -> tuple[str, str]:
    subject = "Checklist 20 lỗi trình bày trước khi nộp"
    body = (f"Chào {name or 'bạn'},\n\nChecklist bạn yêu cầu ở ngay bên dưới.\n\n{checklist_text.strip()}\n\n"
            "Nếu muốn nhận thông tin về dịch vụ hỗ trợ bản thảo, trả lời \"CÓ\"." + footer(business, owner))
    return subject, body


def services_info(name: str, business: str, owner: str, line: str = "A", sender: str = "") -> tuple[str, str]:
    subject = f"{QC}{business}: bảng giá và cách đặt"
    if line == "B":
        how = ("Cách đặt: gửi tệp vào thư này (Word để chuyển phông/biên tập; PDF hoặc ảnh chụp để số hoá), hệ thống báo giá tự "
               "động kèm mã QR. Chuyển phông dưới 50 trang miễn phí. Khối lượng lớn (cả bộ sử liệu của xã mới) hệ thống gửi phiếu "
               "đề xuất để cơ quan làm hợp đồng.\n\n" + POLICY_B)
    else:
        how = "Cách đặt: gửi bản thảo vào thư này, hệ thống báo giá tự động kèm mã QR thanh toán.\n\n" + POLICY
    body = (f"Chào {name or 'bạn'},\n\nCảm ơn bạn đã đồng ý nhận thông tin. Bảng giá:\n" + price_table(line) + "\n" + how
            + marketing_footer(business, owner, sender))
    return subject, body


def outreach_referrer(name: str, business: str, owner: str, owner_title: str, signup_hint: str, sender: str = "") -> tuple[str, str]:
    subject = f"{QC}Xin gửi anh/chị một tài liệu nhỏ cho học viên"
    body = (f"Kính gửi anh/chị {name},\n\n"
            "Thời gian qua tôi thấy nhiều học viên bị trả bài vì lỗi trình bày và trích dẫn hơn là vì nội dung. "
            "Tôi soạn checklist \"20 lỗi trình bày hay bị hội đồng bắt\", tặng miễn phí: " + signup_hint + "\n\n"
            "Nếu anh/chị thấy hữu ích, mong anh/chị chia sẻ cho học viên. Đoạn tin ngắn để dán vào nhóm lớp:\n"
            f"  \"Checklist 20 lỗi trình bày hay bị hội đồng bắt của {owner_title or owner}, tặng miễn phí: {signup_hint}\"\n\n"
            "Tôi cũng vừa mở dịch vụ hỗ trợ hoàn thiện hồ sơ bảo vệ: định dạng theo Thông tư, tài liệu tham khảo, quyển tóm tắt "
            "và bản tiếng Anh, trang đóng góp mới, luyện phản biện. Dịch vụ do trợ lý AI thực hiện, có kiểm tra tự động, "
            "không viết hộ nội dung.\n\n"
            "Nếu anh/chị không muốn nhận thư như thế này, chỉ cần trả lời \"KHÔNG\", tôi sẽ không gửi nữa.\n\n"
            f"Trân trọng,\n{owner_title or owner}" + marketing_footer(business, owner, sender))
    return subject, body


def outreach_learner(name: str, business: str, owner: str, owner_title: str, signup_hint: str, sender: str = "") -> tuple[str, str]:
    subject = f"{QC}Checklist 20 lỗi trình bày trước khi nộp"
    body = (f"Chào {name},\n\nMình vừa soạn checklist \"20 lỗi trình bày hay bị hội đồng bắt\", gửi {name} dùng thử trước khi nộp: "
            f"{signup_hint}\n\nMình có dịch vụ rà định dạng, tài liệu tham khảo, quyển tóm tắt và bản tiếng Anh, do trợ lý AI thực hiện, "
            f"không viết hộ. Nếu {name} muốn nhận thông tin về dịch vụ, trả lời \"CÓ\"; nếu không, cứ bỏ qua thư này, "
            f"mình sẽ không gửi thêm.\n\n{owner_title or owner}" + marketing_footer(business, owner, sender))
    return subject, body


def outreach_local_history(name: str, business: str, owner: str, owner_title: str, alias: str, sender: str = "") -> tuple[str, str]:
    subject = f"{QC}Chuyển phông .VnTime sang Unicode miễn phí cho tài liệu lịch sử địa phương"
    body = (f"Kính gửi anh/chị {name},\n\n"
            "Sau sắp xếp đơn vị hành chính, nhiều xã, phường mới cần tập hợp sử liệu của các đơn vị cũ, trong đó không ít "
            "văn bản gõ bằng phông .VnTime, VNI nay mở ra bị lỗi chữ. Tôi xin gửi tặng công cụ chuyển phông sang Unicode MIỄN PHÍ "
            f"(tệp Word tới 50 trang): gửi tệp tới {alias}, tiêu đề CHUYEN PHONG, hệ thống gửi lại bản Unicode trong ít phút, "
            "chuyển ngay trên máy chủ của dịch vụ, không dùng AI, không lưu tệp.\n\n"
            "Ngoài ra, chúng tôi hỗ trợ người biên soạn: số hoá bản in cũ (nhận dạng chữ, xuất Word), lập biên niên sự kiện hợp "
            "nhất từ lịch sử các xã cũ kèm bảng các chỗ nguồn ghi khác nhau và bảng mốc truyền thống của từng đơn vị cũ, biên tập "
            "kỹ thuật bản thảo và bảng tra cứu nhân danh, địa danh. Chỉ nhận tài liệu không mật, đã công bố hoặc được phép sử dụng.\n\n"
            "Nếu anh/chị muốn nhận bảng giá, xin trả lời \"CÓ\". Nếu không muốn nhận thư như thế này, trả lời \"KHÔNG\", "
            "tôi sẽ không gửi nữa.\n\n"
            f"Trân trọng,\n{owner_title or owner}" + marketing_footer(business, owner, sender))
    return subject, body


def project_proposal(name: str, business: str, owner: str, pages: int, estimate_vnd: int, services: list[str]) -> tuple[str, str]:
    subject = f"{business}: phiếu đề xuất cho khối lượng {pages} trang"
    body = (f"Chào {name or 'anh/chị'},\n\nKhối lượng tài liệu khoảng {pages} trang, vượt mức xử lý tự động của một đơn. "
            f"Hệ thống gửi kèm phiếu đề xuất (đơn giá, dự toán khoảng {fmt_vnd(estimate_vnd)}, tiến độ, cam kết bảo mật) để cơ quan "
            "xem xét; người phụ trách dịch vụ sẽ liên hệ qua email để thống nhất hợp đồng.\n\nCông việc đề xuất:\n"
            + service_lines(services) + "\n\n" + POLICY_B + footer(business, owner))
    return subject, body


def owner_lead(customer: str, email: str, pages: int, estimate_vnd: int, services: list[str]) -> tuple[str, str]:
    subject = f"[CƠ HỘI] Dự án {fmt_vnd(estimate_vnd)}: {customer or email}"
    body = (f"Khách {customer or ''} <{email}> gửi khối lượng {pages} trang, cần:\n{service_lines(services)}\n\n"
            f"Hệ thống đã gửi phiếu đề xuất, dự toán {fmt_vnd(estimate_vnd)} (giá niêm yết). Việc của bạn nếu muốn nhận: trả lời "
            "khách để thống nhất hợp đồng. Với cơ quan nhà nước, gói nhỏ (khoảng dưới 100 triệu đồng theo quy định mua sắm hiện "
            "hành, nhờ kế toán cơ quan xác nhận) làm thủ tục đơn giản hơn; cần xuất được hoá đơn điện tử. Không chia nhỏ gói "
            "để lách quy định đấu thầu.\n\n-- automaton51")
    return subject, body


def ads_notice(budget_vnd: int, total_vnd: int, days: int, post_preview: str, growth_left: str) -> tuple[str, str]:
    subject = f"[THÔNG BÁO] Đã chạy quảng cáo {fmt_vnd(budget_vnd)} trong {days} ngày"
    body = (f"Hệ thống vừa chạy quảng cáo tăng tương tác cho bài:\n  \"{post_preview[:160]}\"\n\n"
            f"Ngân sách trọn đợt {fmt_vnd(budget_vnd)} (cộng thuế GTGT 10% Meta thu: {fmt_vnd(total_vnd)}), trích từ Quỹ mở rộng 49%. "
            f"Quỹ chủ sở hữu 51% không bị đụng tới. Quỹ mở rộng còn {growth_left}.\n"
            "Bạn không cần làm gì. Muốn dừng quảng cáo: đặt ads_enabled = false trong cấu hình hoặc tắt trong Trình quản lý "
            "quảng cáo.\n\n-- automaton51")
    return subject, body
