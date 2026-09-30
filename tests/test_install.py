"""Cài đặt, chạy bền trên Windows/Mac và xử lý sự cố hạ tầng (hết tiền API, sai khoá, mất mạng)."""
import io
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from automaton51 import cli
from automaton51.config import Config
from automaton51.constitution import sha256_file, verify_integrity
from automaton51.ops.engine import infra_problem
from automaton51.ops.mail import Attachment
from automaton51.state import StateDir

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ops import ALIAS, make_env, step, thesis  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn(*a, **kw)
    return result, buf.getvalue()


class SealTests(unittest.TestCase):
    def test_hash_ignores_windows_line_endings(self):
        d = Path(tempfile.mkdtemp())
        (d / "lf.txt").write_bytes(b"dong 1\ndong 2\n")
        (d / "crlf.txt").write_bytes(b"dong 1\r\ndong 2\r\n")
        self.assertEqual(sha256_file(d / "lf.txt"), sha256_file(d / "crlf.txt"))

    def test_repo_seal_is_valid(self):
        ok, problems = verify_integrity()
        self.assertTrue(ok, problems)


class ProcessClaimTests(unittest.TestCase):
    def _sleeper(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        time.sleep(0.3)
        return p

    def test_live_owner_blocks_second_instance(self):
        state = StateDir(Path(tempfile.mkdtemp())).ensure()
        p = self._sleeper()
        state.pid_path.write_text(str(p.pid))  # tiến trình tạo TRƯỚC khi ghi tệp -> đúng chủ
        with self.assertRaises(RuntimeError):
            state.claim_process()
        self.assertEqual(state.running_pid(), p.pid)

    def test_pid_reused_after_reboot_is_taken_over(self):
        state = StateDir(Path(tempfile.mkdtemp())).ensure()
        state.pid_path.write_text("0")
        old = time.time() - 3600
        os.utime(state.pid_path, (old, old))  # tệp PID cũ từ trước khi "khởi động lại máy"
        p = self._sleeper()  # một tiến trình khác tình cờ nhận lại đúng số PID đó
        state.pid_path.write_text(str(p.pid))
        os.utime(state.pid_path, (old, old))
        self.assertIsNone(state.running_pid())
        state.claim_process()  # không bị chặn
        self.assertEqual(state.pid_path.read_text(), str(os.getpid()))
        state.release_process()

    def test_restart_request_consumed_once_and_cleared_on_claim(self):
        state = StateDir(Path(tempfile.mkdtemp())).ensure()
        state.request_restart()
        state.claim_process()  # lần khởi động mới đáp ứng luôn yêu cầu cũ
        self.assertFalse(state.restart_path.exists())
        state.request_restart()
        self.assertTrue(state.consume_restart_request())
        self.assertFalse(state.consume_restart_request())
        state.release_process()

    def test_run_loop_exits_on_restart_request(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        real_tick = auto.tick

        def tick():
            rep = real_tick()
            if rep.tick == 3:  # chủ sở hữu đổi thông tin trong lúc AI đang chạy
                state.request_restart()
            return rep
        auto.tick = tick
        rep = auto.run(max_ticks=50)
        self.assertEqual(rep.tick, 3)  # thoát ngay sau nhịp đó để trình bao (.bat/systemd/launchd) bật lại
        self.assertFalse(state.restart_path.exists())
        self.assertFalse(state.pid_path.exists())

    def test_cmd_run_returns_75_when_already_running(self):
        state, cfg, clock, mail, bank, ops, auto = make_env()
        p = self._sleeper()
        state.pid_path.write_text(str(p.pid))
        args = NS(mode=None, no_brain=True, realtime=False, serve=False, port=None, host="127.0.0.1", ticks=1)
        code, out = quiet(cli.cmd_run, args, state)
        self.assertEqual(code, cli.EXIT_ALREADY_RUNNING)
        self.assertIn(str(p.pid), out)


class SetupTests(unittest.TestCase):
    def _setup(self, root, answers, env=None, **over):
        args = dict(email=None, alias=None, alias_tag=None, owner=None, business=None, notify_email=None, bank=None,
                    account=None, account_name=None, payment_provider=None, facebook_page_id=None, seed_usd=None,
                    from_install=True)
        args.update(over)
        feed = iter(answers)

        def fake_ask(prompt, default="", secret=False):
            val = next(feed)
            return (val or default).strip()
        with mock.patch.object(cli, "_ask", side_effect=fake_ask), mock.patch.dict(os.environ, env or {}, clear=False):
            for var in ("ANTHROPIC_API_KEY", "AUTOMATON51_EMAIL_APP_PASSWORD", "SEPAY_API_TOKEN", "FACEBOOK_PAGE_TOKEN"):
                if var not in (env or {}):
                    os.environ.pop(var, None)
            code, out = quiet(cli.cmd_setup, NS(**args), StateDir(root))
            envfile = (root / ".env").read_text(encoding="utf-8") if (root / ".env").exists() else ""
        return code, out, Config.load(root / "config.json"), envfile

    def test_interactive_setup_normalises_input(self):
        root = Path(tempfile.mkdtemp()) / "st"
        answers = ["Chu@Gmail.com ", "TS. Nguyễn Văn Đức", "vcb", "0123 456 789", "Nguyễn Văn Đức",
                   "sk-ant-api03-abc", "abcd efgh ijkl mnop", "", "", "25"]
        code, out, cfg, envfile = self._setup(root, answers)
        self.assertEqual(code, 0, out)
        self.assertEqual((cfg.email_address, cfg.email_alias, cfg.bank_id, cfg.bank_account_number, cfg.bank_account_name),
                         ("chu@gmail.com", "chu+hocthuat@gmail.com", "970436", "0123456789", "NGUYEN VAN DUC"))
        self.assertIn("AUTOMATON51_EMAIL_APP_PASSWORD=abcdefghijklmnop", envfile)
        self.assertIn("ANTHROPIC_API_KEY=sk-ant-api03-abc", envfile)
        self.assertNotIn("Bước tiếp theo", out)  # gọi từ install: không in hướng dẫn lệnh gõ tay
        from automaton51.ledger import Ledger
        self.assertEqual(str(Ledger(root / "ledger.jsonl").balance("operating")), "25.000000")

    def test_rerun_keeps_values_and_updates_alias_when_email_changes(self):
        root = Path(tempfile.mkdtemp()) / "st"
        first = ["chu@gmail.com", "TS. A", "vcb", "0123456789", "NGUYEN VAN A", "sk-ant-1", "abcdabcdabcdabcd", "", "", "20"]
        self._setup(root, first)
        env = {"ANTHROPIC_API_KEY": "sk-ant-1", "AUTOMATON51_EMAIL_APP_PASSWORD": "abcdabcdabcdabcd"}
        # Lần 2: Enter hết (giữ nguyên), chỉ đổi số tài khoản
        code, out, cfg, envfile = self._setup(root, ["", "", "", "9999888877", "", "", "", "", ""], env=env)
        self.assertEqual((cfg.email_address, cfg.bank_account_number, cfg.owner_name), ("chu@gmail.com", "9999888877", "TS. A"))
        self.assertIn("ANTHROPIC_API_KEY=sk-ant-1", envfile)
        # Lần 3: đổi Gmail -> địa chỉ nhận khách và email báo cáo đi theo
        code, out, cfg, envfile = self._setup(root, ["moi@gmail.com", "", "", "", "", "", "", "", ""], env=env)
        self.assertEqual((cfg.email_alias, cfg.owner_notify_email), ("moi+hocthuat@gmail.com", "moi@gmail.com"))

    def test_setup_asks_running_agent_to_restart(self):
        root = Path(tempfile.mkdtemp()) / "st"
        answers = ["chu@gmail.com", "TS. A", "vcb", "0123456789", "NGUYEN VAN A", "k", "p", "", "", "20"]
        with mock.patch.object(StateDir, "running_pid", return_value=4242):
            code, out, cfg, envfile = self._setup(root, answers)
        self.assertTrue((root / "RESTART").exists())
        self.assertIn("tự khởi động lại", out)


class InstallTests(unittest.TestCase):
    def test_windows_startup_script(self):
        raw = cli._windows_startup_script(Path(r"C:\Users\Phí Nguyễn\Le-Duan-main\deploy\chay-tren-windows.bat"))
        text = raw.decode("utf-8")
        self.assertTrue(text.startswith("@echo off\r\nchcp 65001 >nul\r\n"))
        self.assertIn('start "automaton51" /min "C:\\Users\\Phí Nguyễn\\', text)  # tiêu đề có ngoặc kép, đường dẫn có dấu
        self.assertEqual(text.count("\n"), text.count("\r\n"))

    def test_launch_agent_plist_is_valid(self):
        xml = cli._launch_agent_plist(Path("/Users/a/Le-Duan"), "/Users/a/Le-Duan/.venv/bin/python", Path("/Users/a/Le-Duan/state"))
        data = plistlib.loads(xml.encode("utf-8"))
        self.assertEqual(data["Label"], cli.LAUNCH_AGENT_LABEL)
        self.assertEqual(data["ProgramArguments"][-4:], ["--state", "/Users/a/Le-Duan/state", "run", "--serve"])
        self.assertTrue(data["KeepAlive"] and data["RunAtLoad"])

    def test_install_linux_flow_with_offline_services(self):
        root = Path(tempfile.mkdtemp()) / "st"
        answers = iter(["chu@gmail.com", "TS. A", "vcb", "0123456789", "NGUYEN VAN A", "", "", "", "", "20"])
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            return NS(returncode=0, stdout="", stderr="")
        with mock.patch.object(cli, "_ask", side_effect=lambda p, d="", secret=False: (next(answers) or d).strip()), \
                mock.patch("subprocess.run", side_effect=fake_run), mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {}, clear=False):
            for var in ("ANTHROPIC_API_KEY", "AUTOMATON51_EMAIL_APP_PASSWORD", "SEPAY_API_TOKEN", "FACEBOOK_PAGE_TOKEN"):
                os.environ.pop(var, None)
            code, out = quiet(cli.cmd_install, NS(), StateDir(root))
        self.assertEqual(code, 3)  # thiếu khoá -> kiểm tra chưa đạt, không tự chạy
        self.assertTrue(any("pip" in c and "-r" in c for c in calls if isinstance(c, list)))
        self.assertIn("[3/5]", out)
        self.assertIn("run --serve", out)
        self.assertEqual(Config.load(root / "config.json").bank_account_name, "NGUYEN VAN A")


class WindowsScriptTests(unittest.TestCase):
    def test_batch_files_are_crlf_ascii_with_valid_labels(self):
        for f in (REPO / "deploy").glob("*.bat"):
            raw = f.read_bytes()
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), f.name)
            text = raw.decode("ascii")
            labels = set(re.findall(r"(?m)^:(\w+)", text))
            self.assertLessEqual(set(re.findall(r"goto (\w+)", text)), labels, f.name)
            self.assertNotIn('if "%CSV%"', text)  # đường dẫn kéo-thả có ngoặc kép sẽ làm hỏng lệnh if

    def test_menu_commands_exist_in_cli(self):
        text = (REPO / "deploy" / "lenh-nhanh-windows.bat").read_text(encoding="ascii")
        used = set(re.findall(r"%A51% (\w[\w-]*)", text))
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
        self.assertLessEqual(used, set(sub.choices), used - set(sub.choices))

    def test_runner_stops_looping_when_already_running(self):
        text = (REPO / "deploy" / "chay-tren-windows.bat").read_text(encoding="ascii")
        self.assertIn(f'if "%errorlevel%"=="{cli.EXIT_ALREADY_RUNNING}" goto already', text)


class InfraProblemTests(unittest.TestCase):
    class APIErr(Exception):
        def __init__(self, msg, status_code=None, body=None):
            super().__init__(msg)
            self.status_code, self.body = status_code, body

    def test_classification(self):
        E = self.APIErr
        self.assertEqual(infra_problem(E("Your credit balance is too low to access the Anthropic API", 400,
                                          {"type": "error", "error": {"type": "invalid_request_error"}})), "billing")
        self.assertEqual(infra_problem(E("x", 402, {"error": {"type": "billing_error"}})), "billing")
        self.assertEqual(infra_problem(E("invalid x-api-key", 401, {"error": {"type": "authentication_error"}})), "auth")
        self.assertEqual(infra_problem(E("Overloaded", 529, {"error": {"type": "overloaded_error"}})), "transient")
        self.assertEqual(infra_problem(ConnectionError("mất mạng")), "transient")
        self.assertIsNone(infra_problem(E("prompt is too long", 400, {"error": {"type": "invalid_request_error"}})))
        self.assertIsNone(infra_problem(ValueError("lỗi dữ liệu")))

    def _paid_order(self):
        env = make_env()
        state, cfg, clock, mail, bank, ops, auto = env
        mail.deliver("an@gmail.com", ALIAS, "Nhờ định dạng", "định dạng luận văn", [Attachment("lv.docx", thesis(state.root).read_bytes())])
        step(auto, clock)
        return env, ops.orders.all()[0]

    def test_out_of_credit_holds_order_and_alerts_owner_once(self):
        (state, cfg, clock, mail, bank, ops, auto), order = self._paid_order()
        real_run = ops.fulfiller.run
        broke = {"on": True}

        def run(*a, **kw):
            if broke["on"]:
                raise self.APIErr("Your credit balance is too low to access the Anthropic API.", 400,
                                  {"type": "error", "error": {"type": "invalid_request_error"}})
            return real_run(*a, **kw)
        ops.fulfiller.run = run
        bank.add(order.price_vnd, order.code)
        for _ in range(5):
            step(auto, clock)
        o = ops.orders.get(order.code)
        self.assertEqual((o.status, o.attempts), ("paid", 0))  # không bị tính là thất bại, không hoàn tiền
        alerts = [m for m in mail.sent if "Hết tiền API Claude" in m.subject]
        self.assertEqual(len(alerts), 1)
        self.assertTrue(alerts[0].subject.startswith("[CẦN BẠN]"))
        self.assertIn("platform.claude.com/settings/billing", alerts[0].text)
        self.assertFalse([m for m in mail.sent if m.to == "an@gmail.com" and "hoàn" in m.subject.lower()])
        broke["on"] = False  # chủ sở hữu nạp tiền -> AI tự làm tiếp
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "delivered")

    def test_network_outage_is_retried_without_counting_attempts(self):
        (state, cfg, clock, mail, bank, ops, auto), order = self._paid_order()
        real_run = ops.fulfiller.run
        n = {"fail": 4}

        def run(*a, **kw):
            if n["fail"] > 0:
                n["fail"] -= 1
                raise ConnectionError("không kết nối được api.anthropic.com")
            return real_run(*a, **kw)
        ops.fulfiller.run = run
        bank.add(order.price_vnd, order.code)
        for _ in range(6):
            step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "delivered")
        self.assertFalse([m for m in mail.sent if m.subject.startswith("[CẦN BẠN]")])



class MissingCodePaymentTests(unittest.TestCase):
    def _quoted(self, from_name="Nguyễn Văn An"):
        env = make_env()
        state, cfg, clock, mail, bank, ops, auto = env
        mail.deliver("an@gmail.com", ALIAS, "Nhờ định dạng", "định dạng luận văn",
                     [Attachment("lv.docx", thesis(state.root).read_bytes())], from_name=from_name)
        step(auto, clock)
        return env, ops.orders.all()[0]

    def test_auto_match_by_exact_amount_and_sender_name(self):
        (state, cfg, clock, mail, bank, ops, auto), order = self._quoted()
        bank.add(order.price_vnd, "MBVCB.1234.NGUYEN VAN AN chuyen tien.CT tu 0011")
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "delivered")
        self.assertFalse([m for m in mail.sent if m.subject.startswith("[CẦN BẠN]")])

    def test_uncertain_match_asks_owner_then_paid_command_completes(self):
        (state, cfg, clock, mail, bank, ops, auto), order = self._quoted(from_name="An")
        bank.add(order.price_vnd, "chuyen tien luan van")
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "quoted")
        asks = [m for m in mail.sent if m.subject.startswith("[CẦN BẠN] Tiền vào thiếu mã đơn")]
        self.assertEqual(len(asks), 1)
        self.assertIn(f"automaton51 paid {order.code}", asks[0].text)
        self.assertEqual(ops.ledger.totals()["revenue"], 0)  # chưa xác nhận thì chưa ghi doanh thu
        ops.record_manual_payment(order.code)
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "delivered")
        with self.assertRaises(ValueError):  # giao dịch đã dùng, không khớp lần hai
            ops.record_manual_payment(order.code)

    def test_personal_money_with_other_amount_is_ignored_silently(self):
        (state, cfg, clock, mail, bank, ops, auto), order = self._quoted()
        before = len(mail.sent)
        bank.add(123_000, "NGUYEN VAN AN tra tien an trua")
        step(auto, clock)
        self.assertEqual(ops.orders.get(order.code).status, "quoted")
        self.assertEqual(len(mail.sent), before)


if __name__ == "__main__":
    unittest.main()
