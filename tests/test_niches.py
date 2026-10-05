"""Hai ngách song song (A: hồ sơ bảo vệ luận án; B: sử liệu địa phương), chuyển phông tại máy,
chặn tài liệu mật / hồ sơ cá nhân, chia tỷ trọng theo lãi gộp và quảng cáo trích Quỹ mở rộng 49%."""
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from xml.sax.saxutils import escape

from automaton51 import cli
from automaton51.money import D
from automaton51.ops import templates as T
from automaton51.ops.ads import AdsError, MetaAds, boost_payloads, minor_units
from automaton51.ops.docx_tools import qa_check, read_docx, read_text_any, read_xlsx
from automaton51.ops.facebook import FacebookPublisher, tagged_posts
from automaton51.ops.fulfillment import FulfillmentError, SimFulfiller, plan_groups, skills_for, vision_blocks
from automaton51.ops.intake import classify_rules, is_classified, is_personnel
from automaton51.ops.legacy_fonts import (convert_docx, convert_plain, detect, docx_legacy_report, tcvn3_to_unicode,
                                          vni_to_unicode)
from automaton51.ops.mail import Attachment
from automaton51.ops.orders import SERVICES, expand_services, line_of, price_vnd, quote_total
from automaton51.ops.outreach import classify_contact
from automaton51.ops.sample import make_docx, make_xlsx, sample_legacy_paragraphs, sample_thesis_paragraphs
from automaton51.profit_split import settle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ops import ALIAS, make_env, step, thesis  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def legacy_docx(path: Path, paragraphs: list[list[tuple[str, str]]]) -> Path:
    """Tệp Word có run gắn phông: mỗi đoạn là danh sách (chữ, phông) — phông rỗng = không ghi phông."""
    body = ""
    for runs in paragraphs:
        body += "<w:p>"
        for text, font in runs:
            rpr = f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/></w:rPr>' if font else ""
            body += f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
        body += "</w:p>"
    src = make_docx(path, ["x"])
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}><w:body>{body}</w:body></w:document>'.encode()
            zout.writestr(item, data)
    tmp.replace(path)
    return path


def scan_pdf(path: Path, pages: int) -> Path:
    path.write_bytes(b"%PDF-1.4 " + b"/Type /Page " * pages + b"/Type /Pages")
    return path


class LegacyFontTests(unittest.TestCase):
    def test_tables_and_detection(self):
        self.assertEqual(tcvn3_to_unicode("Céng hoµ x· héi chñ nghÜa ViÖt Nam"), "Cộng hoà xã hội chủ nghĩa Việt Nam")
        self.assertEqual(tcvn3_to_unicode("§¶ng bé Tr­êng"), "Đảng bộ Trường")
        self.assertEqual(vni_to_unicode("Ñoäc laäp - Töï do - Haïnh phuùc"), "Độc lập - Tự do - Hạnh phúc")
        self.assertEqual(vni_to_unicode("ñöôïc nhöõng Chæ thò Myõ"), "được những Chỉ thị Mỹ")
        self.assertEqual([detect(t) for t in ("Hà Nội đẹp", "ViÖt Nam", "Vieät Nam", "Nam Dinh")],
                         ["unicode", "tcvn3", "vni", "ascii"])

    def test_unicode_never_damaged(self):
        text = "Hà Nam là quê hương\nĐảng bộ xã Phúc Lợi\nKích thước 5 µm"
        self.assertEqual(convert_plain(text), (text, ""))

    def test_docx_split_runs_upper_font_and_mixed_paragraphs(self):
        root = Path(tempfile.mkdtemp())
        src = legacy_docx(root / "cu.docx", [
            [("Hµ N", ".VnTime"), ("éi", "")],              # Word cắt một từ thành hai run
            [("b¸o c¸o", ".VnTimeH")],                        # phông chữ hoa
            [("Đã là Unicode: Hà Nội", "Times New Roman")],   # đoạn Unicode giữ nguyên
            [("Vieät Nam", "VNI-Times")],
        ])
        self.assertTrue(docx_legacy_report(src).changed)
        rep = convert_docx(src, root / "UNICODE_cu.docx")
        self.assertEqual((rep.paragraphs_converted, rep.tcvn3, rep.vni), (3, 2, 1))
        text = read_docx(root / "UNICODE_cu.docx").accepted_text
        for expected in ("Hà Nội", "BÁO CÁO", "Đã là Unicode: Hà Nội", "Việt Nam"):
            self.assertIn(expected, text)
        with zipfile.ZipFile(root / "UNICODE_cu.docx") as z:
            xml = z.read("word/document.xml").decode()
        self.assertNotIn(".VnTime", xml)
        self.assertNotIn("VNI-Times", xml)
        self.assertFalse(docx_legacy_report(root / "UNICODE_cu.docx").changed)

    def test_single_line_stamp_in_legacy_text_is_detected(self):
        text, enc = convert_plain("UBND X· PHóC LîI\nMËT\nB¸o c¸o tæng kÕt c«ng t¸c §¶ng")
        self.assertEqual(enc, "tcvn3")
        self.assertTrue(is_classified(text))


class PricingTests(unittest.TestCase):
    def test_bundles_apply_only_when_complete(self):
        self.assertEqual(expand_services(["BV"]), ["DF", "TK", "TT", "TA", "DG", "PB"])
        self.assertEqual(quote_total(["BV"], 180), 5_470_000)
        self.assertEqual(sum(price_vnd(s, 180) for s in expand_services(["BV"])), 6_430_000)
        self.assertEqual(quote_total(["LV"], 100), 1_220_000)
        self.assertEqual(quote_total(["XM"], 600), 11_340_000)
        self.assertEqual(quote_total(["DF", "TK"], 84), 920_000)  # thiếu dịch vụ trong gói: không giảm

    def test_free_font_conversion_then_paid(self):
        self.assertEqual((price_vnd("CP", 50), price_vnd("CP", 51), price_vnd("CP", 120)), (0, 50_000, 120_000))

    def test_lines_and_price_table(self):
        self.assertEqual((line_of(["DF", "PB"]), line_of(["DF", "SH"]), line_of(["CP"])), ("A", "B", "B"))
        table = T.price_table()
        for code, spec in SERVICES.items():
            self.assertIn(spec["name"], table, code)
        self.assertNotIn("Chuyển phông", T.price_table("A"))
        self.assertNotIn("Gói sẵn sàng", T.price_table("B"))


class IntakeTests(unittest.TestCase):
    def test_new_services_and_guards(self):
        cases = {
            "Tệp gõ phông .VnTime bị lỗi phông, nhờ chuyển sang Unicode": ("service_request", ["CP"]),
            "Em cần gói sẵn sàng bảo vệ luận án": ("service_request", ["PB", "BV"]),
            "Nhờ dịch quyển tóm tắt luận án sang tiếng Anh": ("service_request", ["TA"]),
            "Nhờ số hóa bản scan và lập biên niên các xã cũ đã sáp nhập": ("service_request", ["SH", "NB"]),
            "Nhận làm luận văn trọn gói không ạ": ("forbidden", []),
            "Gửi anh tài liệu, độ mật: Mật": ("restricted", []),
            "Nhờ số hóa hồ sơ đảng viên của chi bộ": ("restricted", []),
            "Chương 2 viết về thời kỳ hoạt động bí mật của chi bộ, nhờ hiệu đính": ("service_request", ["HD"]),
        }
        for body, (kind, services) in cases.items():
            intent = classify_rules("", body, True)
            self.assertEqual((intent.kind, intent.services), (kind, services), body)
        self.assertTrue(is_classified("UBND XÃ\nMẬT\nBáo cáo"))
        self.assertFalse(is_classified("THỜI KỲ HOẠT ĐỘNG BÍ MẬT 1930–1945"))
        self.assertTrue(is_personnel("Lý lịch đảng viên"))

    def test_contact_groups(self):
        self.assertEqual(classify_contact("Hà", "ha@gmail.com", "Đảng ủy xã Phúc Lợi", "Chánh văn phòng", "", ""), "G")
        self.assertEqual(classify_contact("Lan", "lan@hanoi.gov.vn", "", "", "", ""), "G")
        self.assertEqual(classify_contact("Bình", "binh@hnue.edu.vn", "ĐH Sư phạm", "Giảng viên", "", ""), "A")
        self.assertEqual(classify_contact("Cường", "c@gmail.com", "", "Nghiên cứu sinh", "", ""), "B")


class QATests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.src = make_docx(self.root / "luan_an.docx", sample_thesis_paragraphs(150))

    def test_summary_must_come_from_thesis(self):
        made_up = make_docx(self.root / "TOM_TAT_LUAN_AN_X.docx", ["Một nhận định hoàn toàn mới về kinh tế vĩ mô toàn cầu hiện đại " * 600])
        res = qa_check(["TT"], [self.src], [made_up], "Báo cáo")
        self.assertTrue(any("không có trong luận án" in i for i in res.issues), res.issues)

    def test_contributions_page_needs_english(self):
        only_vi = make_docx(self.root / "THONG_TIN_DONG_GOP_MOI_X.docx", ["Luận án làm rõ vai trò của nguồn tư liệu lưu trữ địa phương " * 4] * 5)
        res = qa_check(["DG"], [self.src], [only_vi], "Báo cáo")
        self.assertIn("trang đóng góp mới thiếu bản tiếng Anh", res.issues)

    def test_digitization_must_cover_pages(self):
        pdf = scan_pdf(self.root / "scan.pdf", 5)
        out = make_docx(self.root / "SO_HOA_X.docx", ["[Trang 1]", "chữ " * 400, "[Trang 2]", "chữ " * 400])
        res = qa_check(["SH"], [pdf], [out], "Báo cáo")
        self.assertTrue(any("thiếu trang" in i for i in res.issues), res.issues)

    def test_chronology_rows_need_sources(self):
        rows = [["Thời gian", "Sự kiện", "Nguồn"]] + [[str(1950 + i), f"Sự kiện {i}", "lịch sử xã"] for i in range(8)]
        x = make_xlsx(self.root / "BIEN_NIEN_X.xlsx", [("Biên niên", rows), ("Nguồn ghi khác nhau", [["a"]])])
        self.assertEqual(len(read_xlsx(x)), 2)
        res = qa_check(["NB"], [self.src], [x], "Báo cáo")
        self.assertTrue(any("không ghi nguồn" in i for i in res.issues), res.issues)

    def test_stop_flag_is_fatal_and_leftover_legacy_fails(self):
        res = qa_check(["SH"], [self.src], [], "PHÁT HIỆN TÀI LIỆU MẬT trong tệp a.pdf")
        self.assertTrue(res.fatal and not res.passed)
        left = legacy_docx(self.root / "UNICODE_x.docx", [[("Hµ Néi", ".VnTime")]])
        self.assertFalse(qa_check(["CP"], [left], [left], "Báo cáo").passed)

    def test_english_summary_must_translate_whole_summary(self):
        summary = make_docx(self.root / "TOM_TAT_LUAN_AN_X_TT.docx", sample_thesis_paragraphs(150))  # khoảng 5.400 chữ
        short = make_docx(self.root / "TOM_TAT_TIENG_ANH_LUAN_AN_X.docx", ["This chapter examines archival sources in local history."] * 40)
        res = qa_check(["TA"], [self.src, summary], [short], "[CẦN BỔ SUNG] phần còn lại")
        self.assertTrue(any("chưa dịch trọn" in i for i in res.issues), res.issues)

    def test_groups_skills_and_vision(self):
        self.assertEqual(plan_groups(["DF", "TK", "TT", "TA", "DG", "PB"]),
                         [("SUA", ["DF", "TK"]), ("TT", ["TT"]), ("TA", ["TA"]), ("DG", ["DG"]), ("PB", ["PB"])])
        self.assertIn("xlsx", [s["skill_id"] for s in skills_for(["NB"], [])])
        pdf, img = scan_pdf(self.root / "a.pdf", 3), self.root / "b.jpg"
        img.write_bytes(b"\xff\xd8")
        blocks = vision_blocks(["SH"], [pdf, img], [NS(id="f1"), NS(id="f2")])
        self.assertEqual([b["type"] for b in blocks], ["document", "image"])
        self.assertEqual(vision_blocks(["DF"], [pdf], [NS(id="f1")]), [])


class FailOnce(SimFulfiller):
    def __init__(self, fail_service: str, **kw):
        super().__init__(**kw)
        self.fail_service, self.failed = fail_service, False

    def run(self, code, services, inputs, out_dir, *a, **kw):
        if services == [self.fail_service] and not self.failed:
            self.failed = True
            self.calls += 1
            self.services_seen.append(list(services))
            self.inputs_seen.append([Path(p).name for p in inputs])
            raise FulfillmentError("lỗi giả lập một phần")
        return super().run(code, services, inputs, out_dir, *a, **kw)


class EngineTests(unittest.TestCase):
    def test_free_font_conversion_runs_locally_without_quote(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        doc = legacy_docx(state.root / "bc.docx", [[(p, ".VnTime")] for p in sample_legacy_paragraphs()])
        mail.deliver("vanphong@gmail.com", ALIAS, "Nhờ chuyển phông", "Tệp gõ phông .VnTime bị lỗi phông, nhờ chuyển sang Unicode",
                     [Attachment("bao_cao_1998.docx", doc.read_bytes())])
        step(auto, clock)
        order = ops.orders.all()[0]
        self.assertEqual((order.price_vnd, order.status), (0, "delivered"))
        self.assertEqual(ops.fulfiller.calls, 0)  # không dùng AI
        delivery = mail.sent[-1]
        files = [p for p in delivery.attachments if p.name.startswith("UNICODE_")]
        self.assertEqual(len(files), 1)
        self.assertIn("Đảng bộ xã Phúc Lợi", read_text_any(files[0]))
        self.assertIn("CÓ", delivery.text)  # mời đồng ý nhận bảng giá
        self.assertFalse(any("Báo giá" in m.subject for m in mail.sent))
        auto.ledger.reload()
        self.assertEqual(auto.ledger.totals()["revenue"], D("0"))
        # lần thứ hai trong 24 giờ: không còn miễn phí, báo giá mức tối thiểu
        mail.deliver("vanphong@gmail.com", ALIAS, "Nhờ chuyển phông tiếp", "chuyển phông tệp nữa", [Attachment("b.docx", doc.read_bytes())])
        step(auto, clock)
        self.assertEqual(ops.orders.all()[-1].price_vnd, 50_000)
        self.assertIn("Báo giá", mail.sent[-1].subject)

    def test_yes_after_free_conversion_gets_b_prices_and_thanks_is_not_revision(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        doc = legacy_docx(state.root / "bc.docx", [[(p, ".VnTime")] for p in sample_legacy_paragraphs()])
        mail.deliver("vp@gmail.com", ALIAS, "Nhờ chuyển phông", "chuyển phông .VnTime giúp", [Attachment("bc.docx", doc.read_bytes())])
        step(auto, clock)
        delivered = mail.sent[-1]
        mail.deliver("vp@gmail.com", ALIAS, "Re: " + delivered.subject, "Có", in_reply_to=delivered.message_id)
        step(auto, clock)
        info = mail.sent[-1]
        self.assertTrue(info.subject.startswith("[QC] "))
        self.assertIn("Số hoá bản scan", info.text)
        order = ops.orders.all()[0]
        self.assertEqual((order.status, order.revisions_used), ("delivered", 0))
        self.assertTrue(ops.outreach.get("vp@gmail.com").consent)
        # khách trả tiền, nhận bài, nhắn "Cảm ơn ạ": không bị coi là yêu cầu sửa
        mail.deliver("an@gmail.com", ALIAS, "Nhờ định dạng", "định dạng luận văn", [Attachment("lv.docx", thesis(state.root).read_bytes())])
        step(auto, clock)
        paid = ops.orders.all()[-1]
        bank.add(paid.price_vnd, paid.code)
        step(auto, clock)
        sent = len(mail.sent)
        mail.deliver("an@gmail.com", ALIAS, f"Re: [{paid.code}] Đã hoàn thành", "Cảm ơn ạ, em nhận được rồi",
                     in_reply_to=mail.sent[-1].message_id)
        step(auto, clock)
        paid = ops.orders.get(paid.code)
        self.assertEqual((paid.status, paid.revisions_used, len(mail.sent)), ("delivered", 0, sent))
        self.assertEqual(ops.fulfiller.calls, 1)

    def test_unicode_file_sent_for_conversion_is_not_charged(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        doc = make_docx(state.root / "u.docx", ["Báo cáo tổng kết công tác Đảng năm 2024"])
        mail.deliver("x@gmail.com", ALIAS, "Chuyển phông", "nhờ chuyển phông tệp này", [Attachment("u.docx", doc.read_bytes())])
        step(auto, clock)
        self.assertEqual([o.status for o in ops.orders.all()], ["declined"])
        self.assertIn("đã là Unicode", mail.sent[-1].subject)

    def test_bundle_runs_each_part_and_retries_only_failed_part(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        ops.fulfiller = FailOnce("TT", charge=ops.charge_fn("xử lý"))
        doc = thesis(state.root, pages=180, n=200)
        mail.deliver("ncs@gmail.com", ALIAS, "Gói sẵn sàng bảo vệ", "Em cần gói sẵn sàng bảo vệ luận án",
                     [Attachment("luan_an.docx", doc.read_bytes())], from_name="NCS An")
        step(auto, clock)
        order = ops.orders.all()[0]
        self.assertEqual((order.services, order.price_vnd), (["DF", "TK", "TT", "TA", "DG", "PB"], 5_470_000))
        self.assertIn("Đã áp dụng Gói sẵn sàng bảo vệ", mail.sent[-1].text)
        bank.add(order.price_vnd, order.code)
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "paid")  # phần TT lỗi: chờ làm lại
        # bản tiếng Anh (TA) chờ quyển tóm tắt tiếng Việt đạt rồi mới dịch, không chạy trên toàn văn
        self.assertEqual(ops.fulfiller.services_seen, [["DF", "TK"], ["TT"], ["DG"], ["PB"]])
        step(auto, clock)
        order = ops.orders.get(order.code)
        self.assertEqual(order.status, "delivered")
        self.assertEqual(ops.fulfiller.services_seen[4:], [["TT"], ["TA"]])  # chỉ làm lại phần chưa đạt, rồi dịch
        ta_inputs = ops.fulfiller.inputs_seen[5]
        self.assertTrue(any(n.startswith(f"TOM_TAT_LUAN_AN_{order.code}") for n in ta_inputs), ta_inputs)
        names = {p.name for p in mail.sent[-1].attachments}
        for prefix in ("KET_QUA_", "TOM_TAT_LUAN_AN_", "TOM_TAT_TIENG_ANH_LUAN_AN_", "THONG_TIN_DONG_GOP_MOI_", "SLIDE_BAO_VE_"):
            self.assertTrue(any(n.startswith(prefix) for n in names), prefix)
        self.assertEqual([n for n in names if n.startswith("BAO_CAO")], [f"BAO_CAO_{order.code}.md"])  # một báo cáo gộp
        # khách yêu cầu sửa: làm lại mọi phần một lần, có ghi chú sửa
        mail.deliver("ncs@gmail.com", ALIAS, f"Re: [{order.code}] Đã hoàn thành", "Nhờ sửa lại mục lục và slide",
                     in_reply_to=mail.sent[-1].message_id)
        step(auto, clock)
        order = ops.orders.get(order.code)
        self.assertEqual((order.status, order.revisions_used), ("delivered", 1))
        self.assertEqual(ops.fulfiller.services_seen[6:], [["DF", "TK"], ["TT"], ["TA"], ["DG"], ["PB"]])
        auto.ledger.reload()
        revenue = [e for e in auto.ledger.entries if e.kind == "revenue"]
        self.assertEqual(revenue[0].meta["line"], "A")
        ai = [e for e in auto.ledger.entries if e.kind == "cost" and e.category == "inference"]
        self.assertTrue(ai and all(e.meta.get("order") == order.code and e.meta.get("line") == "A" for e in ai))
        self.assertIn("Hai ngách", ops.digest_text(clock.now()))

    def test_restricted_requests_are_refused_without_order(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        stamp = make_docx(state.root / "a.docx", ["ĐẢNG ỦY XÃ", "MẬT", "Báo cáo tình hình"])
        legacy_stamp = legacy_docx(state.root / "b.docx", [[("UBND X· PHóC LîI", ".VnTime")], [("MËT", ".VnTime")],
                                                           [("B¸o c¸o tæng kÕt", ".VnTime")]])
        mail.deliver("a@gmail.com", ALIAS, "Nhờ biên tập", "Nhờ biên tập bản thảo lịch sử địa phương", [Attachment("a.docx", stamp.read_bytes())])
        mail.deliver("b@gmail.com", ALIAS, "Nhờ chuyển phông", "chuyển phông giúp", [Attachment("b.docx", legacy_stamp.read_bytes())])
        mail.deliver("c@gmail.com", ALIAS, "Số hóa", "Nhờ số hóa hồ sơ đảng viên", [Attachment("c.pdf", b"%PDF /Type /Page")])
        step(auto, clock)
        self.assertEqual(ops.orders.all(), [])
        refused = [m for m in mail.sent if "không thể nhận tài liệu này" in m.subject]
        self.assertEqual(sorted(m.to for m in refused), ["a@gmail.com", "b@gmail.com", "c@gmail.com"])

    def test_secrecy_found_during_processing_stops_and_refunds(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        pdf = scan_pdf(state.root / "x.pdf", 3)
        mail.deliver("d@gmail.com", ALIAS, "Số hóa", "Nhờ số hóa bản scan", [Attachment("bien_ban_MAT.pdf", pdf.read_bytes())])
        step(auto, clock)
        order = ops.orders.all()[0]
        self.assertEqual((order.services, order.price_vnd), (["SH"], 300_000))
        bank.add(order.price_vnd, order.code)
        step(auto, clock)
        order = ops.orders.get(order.code)
        self.assertEqual((order.status, order.inputs), ("failed", []))
        self.assertEqual(ops.fulfiller.calls, 1)  # không thử lại
        self.assertFalse((state.workspace / "orders" / order.code).exists())
        self.assertTrue(any("Dừng xử lý" in m.subject for m in mail.sent if m.to == "d@gmail.com"))
        self.assertTrue(any("[CẦN BẠN]" in m.subject and order.code in m.subject for m in mail.sent if m.to == "chu@gmail.com"))

    def test_large_local_history_project_gets_proposal(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        mail.deliver("dangUy@gmail.com", ALIAS, "Biên niên", "Nhờ lập biên niên hợp nhất lịch sử 3 xã cũ",
                     [Attachment("lich_su_3_xa.pdf", scan_pdf(state.root / "l.pdf", 520).read_bytes())], from_name="Văn phòng Đảng ủy")
        mail.deliver("ca.nhan@gmail.com", ALIAS, "Số hóa", "Nhờ số hóa bản scan",
                     [Attachment("sach.pdf", scan_pdf(state.root / "s.pdf", 80).read_bytes())])
        step(auto, clock)
        proposal = next(m for m in mail.sent if m.to == "danguy@gmail.com")
        self.assertIn("phiếu đề xuất", proposal.subject)
        self.assertTrue(any(p.name.startswith("DE_XUAT_") for p in proposal.attachments))
        self.assertTrue(any(m.subject.startswith("[CƠ HỘI]") for m in mail.sent if m.to == "chu@gmail.com"))
        split = next(m for m in mail.sent if m.to == "ca.nhan@gmail.com")
        self.assertIn("quá lớn", split.subject)  # 80 trang số hoá: nhờ chia nhỏ, không phải dự án
        statuses = sorted(o.status for o in ops.orders.all())
        self.assertEqual(statuses, ["declined", "proposal"])

    def test_outreach_splits_lines_with_qc_label_and_records_consent(self):
        state, cfg, clock, mail, bank, ops, auto = make_env(business_address="phường Phúc Lợi, Hà Nội")
        ops.outreach.import_rows([
            {"name": "Trần Thị Bình", "email": "binh@hnue.edu.vn", "org": "ĐH Sư phạm", "title": "Giảng viên", "labels": "", "notes": ""},
            {"name": "Lê Văn Hà", "email": "ha.vp@gmail.com", "org": "Đảng ủy phường Phúc Lợi", "title": "Chánh văn phòng",
             "labels": "", "notes": ""},
        ], own_addresses=[cfg.email_address])
        step(auto, clock)
        out = {m.to: m for m in mail.sent}
        self.assertTrue(out["binh@hnue.edu.vn"].subject.startswith("[QC] "))
        g = out["ha.vp@gmail.com"]
        self.assertTrue(g.subject.startswith("[QC] Chuyển phông"))
        self.assertIn("Địa chỉ: phường Phúc Lợi, Hà Nội", g.text)
        self.assertIn("NGỪNG", g.text)
        mail.deliver("ha.vp@gmail.com", ALIAS, "Re: " + g.subject, "Có")
        step(auto, clock)
        info = mail.sent[-1]
        self.assertTrue(info.subject.startswith("[QC] "))
        self.assertIn("Chuyển phông TCVN3/VNI", info.text)
        self.assertNotIn("Gói sẵn sàng bảo vệ", info.text)
        self.assertTrue(ops.outreach.get("ha.vp@gmail.com").consent)

    def test_facebook_alternates_lines_with_line_cta(self):
        state, cfg, clock, mail, bank, ops, auto = make_env(facebook_page_id="123")
        posted = []
        ops.facebook = FacebookPublisher("123", "tok", post=lambda url, data: posted.append(data["message"]) or {"id": f"123_{len(posted)}"},
                                         get=lambda url: {"name": "Trang"})
        ops.line_posts = [("A", "Bài ngách A"), ("B", "Bài ngách B")]
        for _ in range(4):
            step(auto, clock)
            clock.sleep(86400 - 180)
        self.assertEqual([m.split("\n")[0] for m in posted], ["Bài ngách A", "Bài ngách B", "Bài ngách A", "Bài ngách B"])
        self.assertIn("CHUYEN PHONG", posted[1])
        self.assertIn("CHECKLIST", posted[0])
        self.assertEqual([p["line"] for p in state.kv_get("fb_post_log")], ["A", "B", "A", "B"])
        self.assertEqual(len(tagged_posts(REPO / "playbooks" / "launch-kit" / "08-bai-dang-hai-ngach.md")), 12)

    def test_line_weights_follow_margin_with_floor(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        self.assertEqual(ops.line_weights(clock.now()), {"A": 0.5, "B": 0.5})
        ops.ledger.revenue(D("10"), "order", "x", meta={"line": "A"})
        self.assertEqual(ops.line_weights(clock.now()), {"A": 0.75, "B": 0.25})


class AdsTests(unittest.TestCase):
    def _env(self, growth_revenue_usd="100", fail_on=None):
        state, cfg, clock, mail, bank, ops, auto = make_env(facebook_page_id="123", ads_enabled=True, ad_account_id="999")
        ops.facebook = FacebookPublisher("123", "tok", post=lambda url, data: {"id": "123_9"},
                                         get=lambda url: {"reactions": {"summary": {"total_count": 5 if "123_1" in url else 1}},
                                                          "comments": {"summary": {"total_count": 1}}, "shares": {"count": 0}})
        calls = []

        def http(method, url, data):
            calls.append((method, url, data))
            if fail_on and fail_on in url and method == "POST":
                return {"error": {"message": "Invalid parameter", "error_user_msg": "Ngân sách quá thấp"}}
            if method == "GET":
                return {"currency": "VND", "account_status": 1, "name": "TK quảng cáo"}
            return {"id": f"id{len(calls)}"}
        ops.ads = MetaAds("999", "tok", http=http)
        ops.ledger.revenue(D(growth_revenue_usd), "order", "doanh thu", meta={"line": "A"})
        settle(ops.ledger)
        now = clock.now()
        state.kv_set("fb_post_log", [{"id": "123_1", "line": "A", "ts": now, "text": "Bài A hay"},
                                     {"id": "123_2", "line": "A", "ts": now, "text": "Bài A thường"},
                                     {"id": "123_3", "line": "B", "ts": now, "text": "Bài B"}])
        return state, cfg, clock, mail, ops, calls

    def test_boost_best_a_post_from_growth_fund_only(self):
        state, cfg, clock, mail, ops, calls = self._env()
        owner_before = ops.ledger.balance("owner")
        growth_before = ops.ledger.balance("growth")
        self.assertEqual(ops._ads(clock.now()), 1)
        posts = {url.rsplit("/", 1)[-1]: data for method, url, data in calls if method == "POST"}
        budget = int(min(Decimal(700_000), growth_before * 26000 * Decimal("0.5") / Decimal("1.1")))
        budget -= budget % 1000
        self.assertEqual(posts["adsets"]["lifetime_budget"], str(budget))
        self.assertEqual(posts["adcreatives"]["object_story_id"], "123_1")  # bài ngách A nhiều tương tác nhất
        self.assertEqual(posts["campaigns"]["special_ad_categories"], "[]")
        self.assertEqual(json.loads(posts["ads"]["creative"]), {"creative_id": "id4"})
        spend = [e for e in ops.ledger.entries if e.kind == "growth_spend"]
        self.assertEqual((len(spend), spend[0].category, spend[0].meta["vnd"]), (1, "marketing", int(budget * Decimal("1.1"))))
        self.assertEqual(ops.ledger.balance("owner"), owner_before)  # quỹ 51% không đổi
        self.assertLess(ops.ledger.balance("growth"), growth_before)
        self.assertTrue(any(m.subject.startswith("[THÔNG BÁO] Đã chạy quảng cáo") for m in mail.sent))
        self.assertEqual(ops._ads(clock.now() + 3600), 0)  # chưa đủ 7 ngày
        ok, why = ops.ledger.verify_chain()
        self.assertTrue(ok, why)

    def test_meta_error_records_nothing(self):
        state, cfg, clock, mail, ops, calls = self._env(fail_on="adsets")
        self.assertEqual(ops._ads(clock.now()), 0)
        self.assertEqual([e for e in ops.ledger.entries if e.kind == "growth_spend"], [])
        self.assertIn("lỗi", state.kv_get("ads_status"))
        self.assertTrue(any(data and data.get("status") == "PAUSED" for method, url, data in calls))  # dọn chiến dịch dở

    def test_small_growth_fund_waits(self):
        state, cfg, clock, mail, ops, calls = self._env(growth_revenue_usd="5")
        self.assertEqual(ops._ads(clock.now()), 0)
        self.assertEqual([c for c in calls if c[0] == "POST"], [])
        self.assertIn("chờ Quỹ mở rộng", state.kv_get("ads_status"))

    def test_units_and_payloads(self):
        self.assertEqual((minor_units(700_000, "VND", 26000), minor_units(700_000, "USD", 26000)), (700_000, 2692))
        with self.assertRaises(AdsError):
            minor_units(1, "EUR", 26000)
        p = boost_payloads("1_2", 500_000, 0.0, 7, "x")
        targeting = json.loads(p["adset"]["targeting"])
        self.assertEqual((targeting["geo_locations"]["countries"], targeting["targeting_automation"]["advantage_audience"]), (["VN"], 1))
        self.assertEqual((p["adset"]["destination_type"], p["adset"]["end_time"]), ("ON_POST", "1970-01-08T00:00:00+0000"))


class CliTests(unittest.TestCase):
    def test_prices_and_convert(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["prices", "--pages", "180"]), 0)
        self.assertIn("Gói sẵn sàng bảo vệ luận án tiến sĩ: 5.470.000 đ", buf.getvalue())
        root = Path(tempfile.mkdtemp())
        src = legacy_docx(root / "cu.docx", [[("§¶ng bé x· Phóc Lîi", ".VnTime")]])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["convert", str(src)]), 0)
        self.assertIn("Đảng bộ xã Phúc Lợi", read_text_any(root / "UNICODE_cu.docx"))
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
