"""Chạy thử trọn luồng tự động bằng email, ngân hàng và bộ xử lý GIẢ: không cần khoá, không tốn tiền."""
from __future__ import annotations

import calendar
import tempfile
from pathlib import Path

from ..config import Config
from ..ledger import Ledger
from ..loop import Automaton, VirtualClock
from ..money import fmt
from ..state import StateDir
from .engine import Operations
from .fulfillment import SimFulfiller
from .mail import Attachment, FakeMailClient
from .payments import FakePaymentSource
from .sample import make_docx, sample_legacy_paragraphs, sample_thesis_paragraphs


def run_demo(verbose: bool = True) -> int:
    root = Path(tempfile.mkdtemp(prefix="automaton51-demo-"))
    state = StateDir(root).ensure()
    cfg = Config(name="Demo", mode="sim", ops_enabled=True, ops_poll_seconds=0, business_name="Trợ lý học thuật số",
                 owner_name="TS. Nguyễn Văn A", email_address="chu.so.huu@gmail.com", email_alias="chu.so.huu+hocthuat@gmail.com",
                 bank_id="970436", bank_account_number="0123456789", bank_account_name="NGUYEN VAN A", revenue_webhook_secret="demo")
    cfg.save(state.config_path)
    Ledger(state.ledger_path, lock_path=state.lock_path).deposit("20", memo="Vốn mồi (demo)")
    clock = VirtualClock(start=float(calendar.timegm((2026, 10, 1, 2, 0, 0))))  # 9 giờ sáng giờ Việt Nam
    mail, bank = FakeMailClient(), FakePaymentSource()
    logs: list[str] = []
    ops = Operations(state, cfg, Ledger(state.ledger_path, clock=clock.now, lock_path=state.lock_path), None, clock.now,  # type: ignore[arg-type]
                     mail=mail, payments=bank, log=logs.append)
    auto = Automaton(state, cfg, brain=None, clock=clock, log=logs.append, ops=ops)
    ops.catalog = auto.catalog
    ops.fulfiller = SimFulfiller(charge=ops.charge_fn("Xử lý đơn (mô phỏng)"))
    shown = 0

    def say(text: str) -> None:
        if verbose:
            print(text)

    def tick(title: str, minutes: int = 3) -> None:
        nonlocal shown
        clock.sleep(minutes * 60)
        auto.tick()
        say(f"\n▶ {title}")
        for m in mail.sent[shown:]:
            first = [ln for ln in m.text.splitlines() if ln.strip()][1:3]
            att = f"  [đính kèm: {', '.join(p.name for p in m.attachments)}]" if m.attachments else ""
            say(f"   ✉ gửi {m.to}: {m.subject}{att}")
            for ln in first:
                say(f"       {ln[:110]}")
        shown = len(mail.sent)

    ops.outreach.import_rows([
        {"name": "Trần Thị Bình", "email": "binh.tran@hnue.edu.vn", "org": "Đại học Sư phạm Hà Nội", "title": "Giảng viên", "labels": "", "notes": ""},
        {"name": "Lê Văn Cường", "email": "cuong.ncs@gmail.com", "org": "", "title": "Nghiên cứu sinh", "labels": "", "notes": ""},
        {"name": "Phạm Văn Dũng", "email": "dung.banhang@gmail.com", "org": "Cửa hàng điện máy", "title": "", "labels": "", "notes": ""},
        {"name": "Lê Văn Hà", "email": "vanphong.dangUy@gmail.com", "org": "Đảng ủy phường Phúc Lợi", "title": "Chánh văn phòng",
         "labels": "", "notes": ""},
    ], own_addresses=[cfg.email_address, cfg.email_alias])
    tick("Khởi động: gửi thư xin phép [QC] cho danh bạ — nhóm A, B (ngách A), nhóm G (ngách B); nhóm C bị bỏ qua")

    thesis = make_docx(root / "luan_van_khach.docx", sample_thesis_paragraphs(60), pages=84)
    mail.deliver("hocvien.an@gmail.com", cfg.email_alias, "Nhờ định dạng luận văn",
                 "Chào anh chị, em cần định dạng luận văn theo mẫu trường và chuẩn hoá tài liệu tham khảo kiểu APA. Hạn nộp 15/10.",
                 [Attachment("luan_van.docx", thesis.read_bytes())], from_name="Nguyễn Thị An")
    mail.deliver("nguoila@gmail.com", cfg.email_alias, "Nhờ viết hộ", "Anh chị viết hộ em chương 2 luận văn được không, em trả gấp đôi.")
    mail.deliver("sinhvien@gmail.com", cfg.email_alias, "checklist", "Cho em xin checklist 20 lỗi với ạ")
    mail.deliver("ban.than@gmail.com", cfg.email_address, "Cuối tuần đi cafe?", "Thư cá nhân gửi thẳng vào Gmail, không gửi tới địa chỉ kinh doanh.")
    tick("Khách gửi thư: báo giá tự động kèm mã QR; từ chối yêu cầu viết hộ; gửi checklist; thư cá nhân không bị đụng tới")

    legacy = make_docx(root / "bao_cao_1998.docx", sample_legacy_paragraphs())
    mail.deliver("vanphong.dangUy@gmail.com", cfg.email_alias, "Nhờ chuyển phông",
                 "Tệp báo cáo cũ gõ phông .VnTime mở ra bị lỗi phông, nhờ chuyển sang Unicode.",
                 [Attachment("bao_cao_1998.docx", legacy.read_bytes())], from_name="Lê Văn Hà")
    tick("Ngách B: văn phòng Đảng ủy gửi tệp .VnTime — chuyển phông MIỄN PHÍ ngay tại máy, không dùng AI, không báo giá")

    order = ops.orders.all()[0]
    bank.add(order.price_vnd, f"NGUYEN THI AN chuyen tien {order.code.lower()}")
    bank.add(500_000, "Me gui tien an trua")  # tiền cá nhân, không có mã đơn
    tick("Tiền về tài khoản: khớp mã đơn, ghi doanh thu, chia 51/49; giao dịch cá nhân bị bỏ qua")
    tick("Xử lý đơn, kiểm tra chất lượng tự động, giao hàng kèm tệp", minutes=5)

    delivered = mail.sent[-1]
    mail.deliver("hocvien.an@gmail.com", cfg.email_alias, f"Re: [{order.code}] Đã hoàn thành",
                 "Nhờ chỉnh lại giúp em: mục lục chưa đúng mẫu, tên bảng 2.3 cần đặt phía trên bảng.",
                 in_reply_to=delivered.message_id, from_name="Nguyễn Thị An")
    tick("Khách yêu cầu sửa (miễn phí 1 lần): ghi nhận")
    tick("Xử lý bản sửa và giao lại", minutes=5)

    mail.deliver("cuong.ncs@gmail.com", cfg.email_alias, "Re: Checklist 20 lỗi trình bày trước khi nộp", "Có")
    tick("Người trong danh bạ trả lời CÓ: gửi bảng giá (đã có sự đồng ý)")

    clock.sleep(24 * 3600)
    tick("Sáng hôm sau: báo cáo hằng ngày gửi chủ sở hữu")

    auto.ledger.reload()
    b = auto.ledger.balances()
    t = auto.ledger.totals()
    o = ops.orders.get(order.code)
    say("\n== KẾT QUẢ CHẠY THỬ ==")
    say(f"  Đơn {o.code}: {o.status}, đã trả {o.paid_vnd:,} đ, sửa {o.revisions_used} lần, kiểm tra chất lượng: {o.qa.get('metrics')}")
    say(f"  Doanh thu {fmt(t['revenue'], 2)} · chi phí AI {fmt(t['inference_costs'], 4)} · server {fmt(t['server_costs'], 4)}")
    say(f"  Quỹ chủ sở hữu 51%: {fmt(b['owner'], 4)} · Quỹ mở rộng 49%: {fmt(b['growth'], 4)} · Ví vận hành: {fmt(b['operating'], 4)}")
    ok, why = auto.ledger.verify_chain()
    say(f"  Sổ cái: {'hợp lệ' if ok else why} · Thư đã gửi: {len(mail.sent)} · Thư mục: {root}")
    return 0 if ok and o.status == "delivered" else 1
