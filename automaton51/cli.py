"""CLI: automaton51 <lệnh>  (hoặc: python -m automaton51 <lệnh>)"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from . import __version__
from .config import Config
from .constitution import MANIFEST_PATH, verify_integrity, write_manifest
from .ledger import Ledger, LedgerError
from .money import D, ZERO, fmt
from .profit_split import settle
from .replication import list_children
from .revenue import RevenueInbox
from .state import StateDir
from .survival import Tier


# ----------------------------------------------------------------------------- tiện ích
def load_dotenv(path: Path) -> None:
    """Nạp .env đơn giản (KEY=VALUE), không ghi đè biến đã có."""
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def _money_arg(text: str) -> Decimal:
    try:
        v = D(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError(f"Số tiền không hợp lệ: {text}")
    if v <= ZERO:
        raise argparse.ArgumentTypeError("Số tiền phải > 0")
    return v


def _load(state: StateDir) -> Config:
    if not state.exists():
        sys.exit(f"Chưa có tác nhân tại {state.root}. Tạo bằng: automaton51 --state {state.root} init --name ... --seed-usd ...")
    cfg = Config.load(state.config_path)
    problems = cfg.validate()
    if problems:
        sys.exit("Config lỗi:\n  - " + "\n  - ".join(problems))
    return cfg


def _require_integrity() -> None:
    ok, problems = verify_integrity()
    if not ok:
        sys.exit("⛔ HIẾN PHÁP/SỔ CÁI BỊ SỬA — từ chối chạy:\n  - " + "\n  - ".join(problems) +
                 "\nNếu chính bạn (chủ sở hữu) vừa sửa mã, niêm phong lại bằng: automaton51 seal")


def _make_brain(cfg: Config):
    if cfg.mode == "sim":
        from .brain.simulated import SimulatedBrain
        return SimulatedBrain(seed=cfg.sim_seed)
    from .brain.claude import ClaudeBrain
    return ClaudeBrain(model=cfg.model_normal, effort=cfg.effort_normal, max_tokens=cfg.max_tokens,
                       enable_fallbacks=cfg.enable_fallbacks)


def _print_summary(state: StateDir, cfg: Config) -> None:
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    st = state.read_json(state.status_path, {}) or {}
    b = ledger.balances()
    t = ledger.totals()
    tier = st.get("tier") or state.kv_get("survival_tier", "normal")
    alive = state.kv_get("survival_tier", None) != Tier.DEAD.value
    print(f"== {cfg.name} ({cfg.mode}) — {'CÒN SỐNG' if alive else 'ĐÃ CHẾT'} — tầng {tier} — nhịp {st.get('tick', 0)} — sống {st.get('uptime_days', 0)} ngày")
    rw = st.get("runway_days")
    rw_txt = "∞" if rw is None else f"{float(rw):.1f} ngày"
    print(f"  Ví vận hành        : {fmt(b['operating'], 4)}   (đốt/ngày {fmt(st.get('burn_per_day', 0), 4)}, runway {rw_txt})")
    print(f"  Quỹ chủ sở hữu 51% : {fmt(b['owner'], 4)}   (đã nhận {fmt(t['owner_received'], 4)}, đã rút {fmt(t['owner_paid_out'])})")
    print(f"  Quỹ mở rộng 49%    : {fmt(b['growth'], 4)}   (đã nhận {fmt(t['growth_received'], 4)}, đã chi {fmt(t['growth_spent'])}, cứu sinh {fmt(t['rescued'])})")
    print(f"  Doanh thu {fmt(t['revenue'])} | chi phí vận hành {fmt(t['operating_costs'], 4)} (suy luận {fmt(t['inference_costs'], 4)}, server {fmt(t['server_costs'], 4)}) | đã chia {fmt(t['distributed'], 4)}")
    c = st.get("catalog") or {}
    print(f"  Sản phẩm {c.get('products', 0)} (đang bán {c.get('listed', 0)}, đã bán {c.get('sales', 0)}) | việc mở {c.get('jobs_open', 0)} / đã nộp {c.get('jobs_submitted', 0)} / đã trả {c.get('jobs_paid', 0)} | nội dung {c.get('posts', 0)}")
    kids = st.get("children") or []
    if kids:
        print(f"  Tác nhân con: " + ", ".join(f"{k['name']} [{k.get('tier') or '?'}]" for k in kids))
    fr = st.get("funding_requests_pending") or []
    if fr:
        print(f"  ⚠ Yêu cầu nạp vốn đang chờ: " + "; ".join(f"{fmt(r['amount'])} ({r['reason'][:60]})" for r in fr))
    if state.kill_switch_engaged():
        print("  ⏸ Công tắc STOP đang bật (automaton51 resume để chạy lại)")
    if st.get("last_error"):
        print(f"  ✗ Lỗi gần nhất: {st['last_error']}")



# ----------------------------------------------------------------------------- playbook
PLAYBOOK_DIR = Path(__file__).resolve().parent.parent / "playbooks"


def list_playbooks() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not PLAYBOOK_DIR.exists():
        return out
    for path in sorted(PLAYBOOK_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, _ = parse_playbook(path.read_text(encoding="utf-8"))
        out.append((path.stem, meta.get("name", path.stem)))
    return out


def parse_playbook(text: str) -> tuple[dict, str]:
    """Tách phần đầu '---' (name/genesis/market_language) khỏi thân playbook."""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2].lstrip("\n")
    return meta, body


def apply_playbook(state: StateDir, cfg: Config, name: str) -> Config:
    path = PLAYBOOK_DIR / f"{name}.md"
    if not path.exists():
        names = ", ".join(n for n, _ in list_playbooks()) or "(không có)"
        sys.exit(f"Không có playbook '{name}'. Có sẵn: {names}")
    meta, body = parse_playbook(path.read_text(encoding="utf-8"))
    if meta.get("genesis"):
        cfg.genesis_prompt = meta["genesis"]
    if meta.get("market_language"):
        cfg.market_language = meta["market_language"]
    cfg.save(state.config_path)
    state.strategy_path.write_text(body.strip() + "\n", encoding="utf-8")
    return cfg


def cmd_playbook(args, state: StateDir) -> int:
    if args.pb_cmd == "list":
        items = list_playbooks()
        if not items:
            print("Chưa có playbook nào trong thư mục playbooks/.")
        for stem, name in items:
            print(f"- {stem}: {name}")
        print("Áp dụng: automaton51 playbook apply <tên>  |  khi khai sinh: automaton51 init --playbook <tên>")
        return 0
    cfg = _load(state)
    apply_playbook(state, cfg, args.name)
    print(f"✓ Đã áp playbook '{args.name}': STRATEGY.md và nhiệm vụ khai sinh đã cập nhật (AI đọc ở lượt tiếp theo).")
    return 0

# ----------------------------------------------------------------------------- lệnh
def cmd_init(args, state: StateDir) -> int:
    if state.exists() and not args.force:
        sys.exit(f"Đã có tác nhân tại {state.root} (dùng --force để ghi đè config, sổ cái được giữ).")
    state.ensure()
    cfg = Config(name=args.name, owner_name=args.owner or "", owner_contact=args.contact or "",
                 genesis_prompt=args.genesis or Config().genesis_prompt, mode=args.mode,
                 revenue_webhook_secret=secrets.token_hex(16), dashboard_port=args.port)
    if args.model:
        cfg.model_normal = args.model
    cfg.save(state.config_path)
    if args.playbook:
        cfg = apply_playbook(state, cfg, args.playbook)
        print(f"  Playbook: {args.playbook} -> STRATEGY.md + nhiệm vụ khai sinh")
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    if args.seed_usd and args.seed_usd > ZERO:
        ledger.deposit(args.seed_usd, memo="Vốn mồi ban đầu từ chủ sở hữu")
    print(f"✓ Đã khai sinh '{cfg.name}' tại {state.root} (chế độ {cfg.mode})")
    print(f"  Vốn mồi: {fmt(args.seed_usd or 0)} | webhook secret: {cfg.revenue_webhook_secret}")
    if cfg.mode == "live":
        print("  Chế độ live cần ANTHROPIC_API_KEY (đặt trong .env hoặc biến môi trường).")
    print(f"  Chạy: automaton51 --state {state.root} run --serve")
    return 0


EXIT_ALREADY_RUNNING = 75  # tệp chạy-trên-windows.bat dựa vào mã này để không khởi động lặp


def cmd_run(args, state: StateDir) -> int:
    cfg = _load(state)
    _require_integrity()
    if args.mode:
        cfg.mode = args.mode
    from .loop import Automaton, RealClock, VirtualClock
    brain = None if args.no_brain else _make_brain(cfg)
    if cfg.mode == "sim" and not args.realtime:
        # đồng hồ ảo tiếp tục từ lần chạy trước (không bao giờ lùi về quá khứ)
        clock = VirtualClock(start=max(float(state.kv_get("clock_now", 0) or 0), time.time()))
    else:
        clock = RealClock()
    try:
        state.claim_process()
    except RuntimeError as exc:
        print(f"⏸ {exc}")
        return EXIT_ALREADY_RUNNING
    auto = Automaton(state, cfg, brain, clock=clock)
    server = None
    if args.serve:
        from .server import start_background
        try:
            server, _ = start_background(state, cfg, args.port, host=args.host)
            print(f"🌐 Dashboard: http://{'localhost' if args.host in ('127.0.0.1', 'localhost') else args.host}:{args.port or cfg.dashboard_port}/  (cửa hàng: /store)")
        except OSError as exc:  # cổng bận: vẫn chạy kinh doanh, chỉ thiếu bảng điều khiển
            print(f"⚠ Không mở được bảng điều khiển ({exc}); tác nhân vẫn chạy bình thường.")
    print(f"▶ Chạy '{cfg.name}' ({cfg.mode}, {'đồng hồ ảo' if isinstance(clock, VirtualClock) else 'thời gian thật'}). Ctrl+C để dừng.")
    try:
        rep = auto.run(max_ticks=args.ticks)
    except KeyboardInterrupt:
        print("\n⏹ Dừng theo yêu cầu.")
        rep = auto.last_report
    finally:
        if server is not None:
            server.shutdown()
    _print_summary(state, cfg)
    return 0 if (rep is None or not rep.died) else 2


def cmd_simulate(args, state: StateDir) -> int:
    _require_integrity()
    from .brain.simulated import SimulatedBrain
    from .loop import Automaton, VirtualClock
    if args.fresh or not state.exists():
        root = Path(tempfile.mkdtemp(prefix="automaton51-sim-")) if args.fresh else state.root
        state = StateDir(root).ensure()
        cfg = Config(name=args.name, mode="sim", sim_seed=args.seed, owner_name="Chủ sở hữu (mô phỏng)",
                     revenue_webhook_secret=secrets.token_hex(8))
        cfg.save(state.config_path)
        Ledger(state.ledger_path, lock_path=state.lock_path).deposit(args.seed_usd, memo="Vốn mồi mô phỏng")
    else:
        cfg = _load(state)
        cfg.mode = "sim"
    clock = VirtualClock(start=max(float(state.kv_get("clock_now", 0) or 0), time.time()))
    quiet = args.quiet
    auto = Automaton(state, cfg, SimulatedBrain(seed=args.seed), clock=clock, log=(lambda m: None) if quiet else print)
    print(f"▶ Mô phỏng '{cfg.name}' {args.ticks} nhịp × {cfg.sim_tick_minutes} phút ảo, vốn mồi {fmt(args.seed_usd)}, hạt giống {args.seed}, thư mục {state.root}")
    rep = auto.run(max_ticks=args.ticks)
    days = (clock.now() - auto.born_at) / 86400
    print(f"\n== KẾT QUẢ sau {rep.tick} nhịp (~{days:.1f} ngày ảo) ==")
    _print_summary(state, cfg)
    ok, why = auto.ledger.verify_chain()
    print(f"  Chuỗi băm sổ cái: {'hợp lệ' if ok else 'LỖI: ' + why}")
    return 0


def cmd_status(args, state: StateDir) -> int:
    cfg = _load(state)
    _print_summary(state, cfg)
    return 0


def cmd_ledger(args, state: StateDir) -> int:
    _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    if args.verify:
        ok, why = ledger.verify_chain()
        print(("✓ Sổ cái hợp lệ: " if ok else "✗ Sổ cái LỖI: ") + why + f" ({len(ledger.entries)} dòng)")
        return 0 if ok else 3
    for e in ledger.tail(args.tail):
        sign = "+" if e.amount > 0 else ""
        print(f"{e.seq:5d} {time.strftime('%Y-%m-%d %H:%M', time.gmtime(e.ts))} {e.kind:12s} {e.account:9s} {sign}{e.amount:>12.6f} {e.category:12s} {e.memo[:80]}")
    b = ledger.balances()
    print(f"      số dư: vận hành {fmt(b['operating'], 4)} | chủ sở hữu {fmt(b['owner'], 4)} | mở rộng {fmt(b['growth'], 4)}")
    return 0


def cmd_revenue(args, state: StateDir) -> int:
    _load(state)
    inbox = RevenueInbox(state)
    if args.rev_cmd == "add":
        ev = inbox.append(args.amount, source=args.source, memo=args.memo or "", product_id=args.product or "",
                          job_id=args.job or "", external_id=args.external_id or "")
        if ev is None:
            print("Bỏ qua: external_id trùng (đã ghi trước đó).")
        else:
            print(f"✓ Đã ghi doanh thu {fmt(args.amount)} [{args.source}] {args.memo or ''} (id {ev.id}). Vòng lặp sẽ nhận ở nhịp tiếp theo và chia 51/49.")
        return 0
    rows = inbox.all()
    cursor = int(state.kv_get("revenue_cursor", 0) or 0)
    for i, r in enumerate(rows[-args.tail:], start=max(0, len(rows) - args.tail)):
        flag = "đã nhận" if i < cursor else "CHỜ"
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(float(r.get('ts', 0))))} +{fmt(r.get('amount', 0))} [{r.get('source')}] {r.get('memo', '')} ({flag})")
    if not rows:
        print("Chưa có doanh thu nào được ghi.")
    return 0


def cmd_fund(args, state: StateDir) -> int:
    _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    ledger.deposit(args.amount, memo=args.memo or "Chủ sở hữu nạp vốn")
    rows = state.read_jsonl(state.funding_requests_path)
    if any(r.get("status") == "pending" for r in rows):
        for r in rows:
            if r.get("status") == "pending":
                r["status"] = "fulfilled"
                r["fulfilled_at"] = time.time()
        import json
        with open(state.funding_requests_path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✓ Đã nạp {fmt(args.amount)} vào ví vận hành. Số dư: {fmt(ledger.balance('operating'), 4)}")
    if state.kv_get("survival_tier", None) == Tier.DEAD.value:
        print("  Tác nhân đang CHẾT. Hồi sinh bằng: automaton51 resurrect")
    return 0


def cmd_payout(args, state: StateDir) -> int:
    _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    settle(ledger, memo="Chia lợi nhuận 51/49 (trước khi rút)")
    available = ledger.balance("owner")
    amount = args.amount or available
    if amount <= ZERO or amount > available:
        sys.exit(f"Quỹ chủ sở hữu hiện có {fmt(available, 4)}; không thể rút {fmt(amount or 0)}.")
    ledger.payout(amount, memo=args.memo or "Chủ sở hữu rút quỹ 51%")
    print(f"✓ Đã ghi rút {fmt(amount, 4)} từ Quỹ chủ sở hữu (còn {fmt(ledger.balance('owner'), 4)}).")
    print("  Lưu ý: đây là bút toán trong sổ cái; việc chuyển tiền thật về tài khoản của bạn do bạn thực hiện ở cổng thanh toán.")
    return 0


def cmd_withdraw(args, state: StateDir) -> int:
    _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    settle(ledger, memo="Chia lợi nhuận 51/49 (trước khi rút vốn)")
    try:
        ledger.withdraw(args.amount, memo=args.memo or "Chủ sở hữu rút vốn vận hành")
    except LedgerError as exc:
        sys.exit(f"Không rút được: {exc}")
    print(f"✓ Đã rút {fmt(args.amount)} khỏi ví vận hành (còn {fmt(ledger.balance('operating'), 4)}).")
    return 0


def cmd_send(args, state: StateDir) -> int:
    _load(state)
    state.append_jsonl(state.owner_inbox_path, {"ts": time.time(), "text": args.message})
    print("✓ Đã gửi. Tác nhân sẽ đọc ở lượt tiếp theo.")
    return 0


def cmd_serve(args, state: StateDir) -> int:
    cfg = _load(state)
    from .server import serve_forever
    port = args.port or cfg.dashboard_port
    print(f"🌐 Dashboard http://{args.host}:{port}/ · cửa hàng /store · webhook POST /webhook/revenue, /webhook/sepay")
    serve_forever(state, cfg, port, host=args.host)
    return 0


def cmd_seal(args, state: StateDir) -> int:
    manifest = write_manifest()
    print(f"✓ Đã niêm phong {len(manifest)} tệp vào {MANIFEST_PATH}")
    for rel, digest in manifest.items():
        print(f"  {digest[:16]}…  {rel}")
    return 0


def cmd_verify(args, state: StateDir) -> int:
    ok, problems = verify_integrity()
    if ok:
        print("✓ Hiến pháp và các mô-đun được bảo vệ còn nguyên vẹn.")
        return 0
    print("✗ Sai lệch:\n  - " + "\n  - ".join(problems))
    return 3


def cmd_children(args, state: StateDir) -> int:
    _load(state)
    kids = list_children(state)
    if not kids:
        print("Chưa có tác nhân con.")
        return 0
    for k in kids:
        b = k.get("balances") or {}
        print(f"- {k['name']} (thế hệ {k.get('generation')}) [{k.get('tier') or '?'}] vốn mồi {fmt(k['seed'])} | ví vận hành {fmt(b.get('operating', 0))} | quỹ chủ {fmt(b.get('owner', 0))} | {k['path']}")
    return 0


def cmd_stop(args, state: StateDir) -> int:
    _load(state)
    state.kill_switch_path.write_text(f"STOP {time.time()}\n", encoding="utf-8")
    print("⏸ Đã bật công tắc STOP: tác nhân ngừng hành động ở nhịp tiếp theo (nhịp tim vẫn trừ tiền server).")
    return 0


def cmd_resume(args, state: StateDir) -> int:
    _load(state)
    if state.kill_switch_path.exists():
        state.kill_switch_path.unlink()
    print("▶ Đã tắt công tắc STOP.")
    return 0


def cmd_resurrect(args, state: StateDir) -> int:
    _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    if ledger.balance("operating") <= ZERO:
        sys.exit("Ví vận hành = 0. Nạp vốn trước: automaton51 fund <số tiền>")
    state.kv_set("survival_tier", None)
    state.kv_set("zero_since", None)
    ledger.note("resurrect", "Chủ sở hữu hồi sinh tác nhân sau khi nạp vốn")
    print("✓ Đã hồi sinh. Chạy lại: automaton51 run")
    return 0



# ----------------------------------------------------------------------------- vận hành tự động
BANK_BINS = {
    "vietcombank": "970436", "vcb": "970436", "vietinbank": "970415", "icb": "970415", "bidv": "970418",
    "agribank": "970405", "vba": "970405", "mb": "970422", "mbbank": "970422", "techcombank": "970407", "tcb": "970407",
    "acb": "970416", "vpbank": "970432", "vpb": "970432", "tpbank": "970423", "tpb": "970423", "sacombank": "970403",
    "stb": "970403", "vib": "970441", "shb": "970443", "hdbank": "970437", "hdb": "970437", "ocb": "970448", "msb": "970426",
    "seabank": "970440", "eximbank": "970431", "lpbank": "970449", "namabank": "970428", "bacabank": "970409",
}


def _write_env(path: Path, values: dict) -> None:
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update({k: v for k, v in values.items() if v})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in existing.items()), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    if not sys.stdin.isatty():
        return default
    import getpass
    suffix = f" [{default}]" if default and not secret else ""
    val = getpass.getpass(f"{prompt}: ") if secret else input(f"{prompt}{suffix}: ")
    return (val or default).strip()


def cmd_setup(args, state: StateDir) -> int:
    from .ops import secrets as S
    state.ensure()
    cfg = Config.load(state.config_path) if state.exists() else Config(revenue_webhook_secret=secrets.token_hex(16))
    print("== Cài đặt vận hành tự động (một lần) ==")
    print("Bạn chỉ cần chỉ định tài khoản nhận tiền và các khoá kết nối. Mọi việc khác chạy tự động.\n")
    old_email = cfg.email_address
    cfg.email_address = (args.email or _ask("Gmail dùng cho kinh doanh", old_email)).strip().lower()
    if not cfg.email_address or "@" not in cfg.email_address:
        sys.exit("Cần địa chỉ Gmail hợp lệ (--email).")
    local, _, domain = cfg.email_address.partition("@")
    tag = args.alias_tag or "hocthuat"
    if args.alias or not cfg.email_alias or cfg.email_address != old_email:
        cfg.email_alias = (args.alias or f"{local}+{tag}@{domain}").lower()
    cfg.owner_name = args.owner or _ask("Tên bạn (ký tên trong thư, ví dụ: TS. Nguyễn Văn A)", cfg.owner_name)
    cfg.business_name = args.business or cfg.business_name
    cfg.owner_contact = cfg.email_alias
    if args.notify_email:
        cfg.owner_notify_email = args.notify_email
    elif not cfg.owner_notify_email or cfg.owner_notify_email == old_email:
        cfg.owner_notify_email = cfg.email_address
    print("\n-- Tài khoản nhận tiền (việc duy nhất bạn tự chỉ định) --")
    bank = (args.bank or _ask("Ngân hàng (vcb, tcb, mbbank, acb, bidv, vietinbank, vpbank, tpbank... hoặc BIN 6 số)",
                              cfg.bank_id)).strip().lower()
    cfg.bank_id = BANK_BINS.get(bank.replace(" ", ""), bank)
    account = args.account or _ask("Số tài khoản (KHÔNG nên trùng số điện thoại)", cfg.bank_account_number)
    cfg.bank_account_number = "".join(account.split()).replace(".", "").replace("-", "")
    from .ops.intake import fold
    raw_name = args.account_name or _ask("Tên chủ tài khoản (ví dụ: NGUYEN VAN A)", cfg.bank_account_name)
    cfg.bank_account_name = " ".join(fold(raw_name).upper().split())
    if args.facebook_page_id:
        cfg.facebook_page_id = args.facebook_page_id
    cfg.mode = "live"
    cfg.ops_enabled = True
    cfg.payment_provider = args.payment_provider or cfg.payment_provider or "sepay"
    cfg.agent_turn_interval_minutes = cfg.agent_turn_interval_minutes or 360
    cfg.name = cfg.name if cfg.name != "Automaton-51" else "Tro-ly-hoc-thuat"
    cfg.save(state.config_path)
    apply_playbook(state, cfg, "tro-ly-hoc-thuat")
    cfg = Config.load(state.config_path)

    print("\n-- Khoá kết nối (lưu vào tệp .env trong thư mục state, quyền 600, không đưa lên GitHub) --")
    env_values = {}
    for var, prompt in ((S.ENV_ANTHROPIC, "Khoá API Claude (platform.claude.com/settings/keys, bắt đầu bằng sk-ant-)"),
                        (S.ENV_EMAIL_PASSWORD, "Mật khẩu ứng dụng Gmail (16 chữ, myaccount.google.com/apppasswords)"),
                        (S.ENV_SEPAY_TOKEN, "API token SePay, để AI tự thấy tiền khách chuyển (my.sepay.vn > Cấu hình Công ty > API Access) — chưa có thì Enter, làm sau"),
                        (S.ENV_FACEBOOK_TOKEN, "Page access token Facebook — Enter để bỏ qua")):
        current = S.get(var)
        hint = f" [đang có {S.mask(current)} — Enter để giữ]" if current else ""
        val = (_ask(prompt + hint, secret=True) or current or "").strip()
        if var == S.ENV_EMAIL_PASSWORD:
            val = val.replace(" ", "")  # Google hiển thị dạng "abcd efgh ijkl mnop"
        if val:
            env_values[var] = val
            os.environ[var] = val
    _write_env(state.root / ".env", env_values)
    if S.get(S.ENV_FACEBOOK_TOKEN) and not cfg.facebook_page_id:
        page_id = _ask("ID Trang Facebook (dãy số, xem ở phần Giới thiệu của Trang) — Enter để bỏ qua").strip()
        if page_id:
            cfg.facebook_page_id = page_id
            cfg.save(state.config_path)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    seed = args.seed_usd
    if seed is None and not ledger.entries:
        ans = _ask("Số tiền bạn đã nạp vào tài khoản API Claude, tính bằng USD (vốn mồi)", "20")
        try:
            seed = _money_arg(ans) if ans else None
        except argparse.ArgumentTypeError:
            seed = None
    if seed and ledger.balance("operating") <= ZERO and not ledger.entries:
        ledger.deposit(seed, memo="Vốn mồi (tương ứng tiền nạp API Claude)")
    _setup_optional(args, state, cfg)
    problems = cfg.validate()
    print("\n✓ Đã lưu cấu hình." if not problems else "\n⚠ Còn thiếu:\n  - " + "\n  - ".join(problems))
    from .ops.payments import vietqr_url
    print(f"  Địa chỉ nhận khách: {cfg.email_alias}")
    print(f"  Mã QR mẫu (mở bằng trình duyệt, quét thử bằng app ngân hàng để kiểm tra đúng tên và số tài khoản):")
    print(f"    {vietqr_url(cfg.bank_id, cfg.bank_account_number, cfg.bank_account_name, 10000, 'HTTHU01')}")
    print(f"  Khoá đã có: " + ", ".join(f"{k}={S.mask(S.get(k))}" for k in S.ALL))
    if state.running_pid():
        state.request_restart()
        print("  ↻ AI đang chạy sẽ tự khởi động lại trong vài phút để dùng thông tin mới.")
    if not getattr(args, "from_install", False):
        print("\nBước tiếp theo:\n  1) automaton51 doctor        (kiểm tra mọi kết nối)"
              "\n  2) automaton51 outreach import danh-ba.csv   (tuỳ chọn: CSV xuất từ contacts.google.com)"
              "\n  3) automaton51 run --serve   (chạy mãi; hoặc cài dịch vụ 24/7, xem deploy/)")
    return 0 if not problems else 1


def _setup_optional(args, state: StateDir, cfg: Config) -> None:
    """Tuỳ chọn ở cuối setup (Enter để bỏ qua): thông tin người gửi in trong thư quảng cáo, quảng cáo trả tiền Meta."""
    from .ops import secrets as S
    print("\n-- Tuỳ chọn (Enter để bỏ qua): thông tin người gửi trong thư quảng cáo, quảng cáo trả tiền --")
    address, website, phone = (getattr(args, k, None) for k in ("address", "website", "phone"))
    cfg.business_address = (address if address is not None else
                            _ask("Địa chỉ liên hệ kinh doanh, in cuối thư quảng cáo (ví dụ: phường Phúc Lợi, Hà Nội)",
                                 cfg.business_address)).strip()
    cfg.business_website = (website if website is not None else
                            _ask("Địa chỉ Trang Facebook của dịch vụ (https://facebook.com/...)", cfg.business_website)).strip()
    cfg.business_phone = (phone if phone is not None else
                          _ask("Số điện thoại RIÊNG cho kinh doanh nếu có (KHÔNG dùng số cá nhân)", cfg.business_phone)).strip()
    current = S.get(S.ENV_META_ADS)
    hint = f" [đang có {S.mask(current)} — Enter để giữ]" if current else ""
    token = (_ask("Token quảng cáo Meta (người dùng hệ thống, quyền ads_management)" + hint, secret=True) or current or "").strip()
    if token and token != current:
        _write_env(state.root / ".env", {S.ENV_META_ADS: token})
        os.environ[S.ENV_META_ADS] = token
    ad_account = (getattr(args, "ad_account", None) or
                  (_ask("Số tài khoản quảng cáo Meta (dãy số sau act_)", cfg.ad_account_id) if token else "")).strip()
    if ad_account and token:
        cfg.ad_account_id = ad_account.replace("act_", "")
        cfg.ads_enabled = True  # chỉ chi từ Quỹ mở rộng 49%, có trần mỗi đợt
        print(f"  Quảng cáo trả tiền: BẬT, tối đa {cfg.ads_weekly_cap_vnd:,} đ mỗi {cfg.ads_every_days} ngày (cộng 10% thuế), "
              "chỉ trích Quỹ mở rộng 49%.".replace(",", "."))
    cfg.save(state.config_path)


def cmd_doctor(args, state: StateDir) -> int:
    from .ops import secrets as S
    from .ops.payments import vietqr_url
    cfg = Config.load(state.config_path) if state.exists() else None
    if cfg is None:
        sys.exit("Chưa cài đặt. Chạy: automaton51 setup")
    bad = 0

    def line(ok, text):
        nonlocal bad
        print(("  ✓ " if ok else "  ✗ ") + text)
        bad += 0 if ok else 1

    print("== Kiểm tra hệ thống ==")
    ok, probs = verify_integrity()
    line(ok, "Hiến pháp và mô-đun 51/49 nguyên vẹn" if ok else "Niêm phong sai: " + "; ".join(probs))
    probs = cfg.validate()
    line(not probs, "Cấu hình hợp lệ" if not probs else "Cấu hình: " + "; ".join(probs))
    line(cfg.ops_enabled, "Vận hành tự động đang BẬT" if cfg.ops_enabled else "Vận hành tự động đang TẮT (chạy automaton51 setup)")
    for var in S.ALL:
        optional = var in (S.ENV_FACEBOOK_TOKEN, S.ENV_SEPAY_WEBHOOK_KEY) or (var == S.ENV_SEPAY_TOKEN and cfg.payment_provider != "sepay") \
            or (var == S.ENV_META_ADS and not cfg.ads_enabled)
        if S.get(var) or not optional:
            line(bool(S.get(var)), f"{var}: {S.mask(S.get(var))}")
    if cfg.outreach_enabled and not cfg.business_address:
        print("  i Thư quảng cáo nên có địa chỉ liên hệ (Nghị định 91/2020): chạy lại setup và điền địa chỉ kinh doanh.")
    if args.offline:
        return 0 if bad == 0 else 3
    if S.get(S.ENV_ANTHROPIC):
        try:
            import anthropic
            client = anthropic.Anthropic()
            m = client.models.retrieve(cfg.fulfillment_model)
            # 1 token với model rẻ nhất (~0,00001 USD) để biết tài khoản có tiền hay chưa
            client.messages.create(model=cfg.model_critical, max_tokens=1, messages=[{"role": "user", "content": "ping"}])
            line(True, f"Claude API: khoá đúng, tài khoản có tiền, dùng được {m.id}")
        except Exception as exc:  # noqa: BLE001
            from .ops.engine import infra_problem
            hint = {"billing": "tài khoản API chưa có tiền — nạp tại https://platform.claude.com/settings/billing",
                    "auth": "khoá sai hoặc đã bị xoá — tạo khoá mới tại https://platform.claude.com/settings/keys",
                    "transient": "không kết nối được máy chủ Claude — kiểm tra Internet rồi thử lại"}.get(infra_problem(exc) or "")
            line(False, f"Claude API: {hint} ({str(exc)[:150]})" if hint else f"Claude API: {exc}")
    if cfg.email_address and S.get(S.ENV_EMAIL_PASSWORD):
        from .ops.mail import GmailClient
        g = GmailClient(cfg.email_address, S.get(S.ENV_EMAIL_PASSWORD), cfg.email_alias, cfg.order_code_prefix,
                        cfg.imap_host, cfg.imap_port, cfg.smtp_host, cfg.smtp_port, from_name=cfg.business_name)
        import imaplib
        import smtplib
        for name, fn in (("Gmail IMAP", g.check_login), ("Gmail SMTP", g.check_smtp)):
            try:
                line(True, f"{name}: {fn()}")
            except Exception as exc:  # noqa: BLE001
                auth = isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) or \
                    any(w in str(exc).lower() for w in ("authenticat", "credentials", "password"))
                hint = ("sai địa chỉ Gmail hoặc mật khẩu ứng dụng — bật xác minh 2 bước rồi tạo lại tại "
                        "https://myaccount.google.com/apppasswords" if auth else
                        "không kết nối được máy chủ Gmail — kiểm tra Internet/tường lửa")
                line(False, f"{name}: {hint} ({str(exc)[:150]})")
    if cfg.payment_provider == "sepay" and S.get(S.ENV_SEPAY_TOKEN):
        from .ops.payments import SePaySource
        try:
            txs = SePaySource(S.get(S.ENV_SEPAY_TOKEN), cfg.bank_account_number, limit=5).fetch()
            line(True, f"SePay: đọc được giao dịch ({len(txs)} giao dịch tiền vào gần nhất)")
        except Exception as exc:  # noqa: BLE001
            line(False, f"SePay: {exc}")
    if cfg.facebook_page_id and S.get(S.ENV_FACEBOOK_TOKEN):
        from .ops.facebook import FacebookPublisher
        try:
            line(True, "Facebook: " + FacebookPublisher(cfg.facebook_page_id, S.get(S.ENV_FACEBOOK_TOKEN), cfg.graph_api_version).check())
        except Exception as exc:  # noqa: BLE001
            line(False, f"Facebook: {exc}")
    if cfg.ads_enabled and cfg.ad_account_id and S.get(S.ENV_META_ADS):
        from .ops.ads import MetaAds
        try:
            line(True, "Quảng cáo Meta: " + MetaAds(cfg.ad_account_id, S.get(S.ENV_META_ADS), cfg.graph_api_version).check())
        except Exception as exc:  # noqa: BLE001
            line(False, f"Quảng cáo Meta: {exc}")
    print("  i Mã QR mẫu: " + vietqr_url(cfg.bank_id, cfg.bank_account_number, cfg.bank_account_name, 10000, "HTTHU01"))
    print("\nKết luận: " + ("sẵn sàng chạy (automaton51 run --serve)" if bad == 0 else f"còn {bad} mục cần sửa"))
    return 0 if bad == 0 else 3


def _ops_for_cli(state: StateDir, cfg: Config):
    from .ops.engine import build_operations
    from .catalog import Catalog
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    return build_operations(state, cfg, ledger, Catalog(state), time.time, log=print)


def cmd_outreach(args, state: StateDir) -> int:
    cfg = _load(state)
    from .ops.outreach import OutreachStore, parse_contacts_csv
    store = OutreachStore(state)
    if args.out_cmd == "import":
        csv_path = Path(args.csv.strip().strip('"'))
        if not csv_path.is_file():
            sys.exit(f"Không thấy tệp {csv_path}. Xuất danh bạ tại https://contacts.google.com (Xuất > Google CSV) rồi thử lại.")
        rows = parse_contacts_csv(csv_path.read_text(encoding="utf-8-sig", errors="ignore"))
        counts = store.import_rows(rows, own_addresses=[cfg.email_address, cfg.email_alias])
        print(f"✓ Đã nhập {len(rows)} liên hệ có email. Nhóm A (người giới thiệu): {counts['A']} · "
              f"nhóm B (khách tiềm năng quen): {counts['B']} · nhóm C (không gửi): {counts['C']} · bỏ qua: {counts['skipped']}")
        print("  Chỉ lưu tên, email và nhóm; không lưu số điện thoại. Có thể xoá tệp CSV sau bước này.")
        print(f"  Hệ thống gửi tối đa {cfg.outreach_daily_limit} thư/ngày, 8–20 giờ, mỗi người đúng một thư xin phép.")
        return 0
    for k, v in sorted(store.stats().items()):
        print(f"  {k}: {v}")
    return 0


def cmd_orders(args, state: StateDir) -> int:
    cfg = _load(state)
    from .ops.orders import OrderStore
    from .ops.templates import fmt_vnd
    orders = OrderStore(state, prefix=cfg.order_code_prefix).all()
    if not args.all:
        orders = [o for o in orders if o.status not in ("closed", "expired", "declined", "refunded")]
    if not orders:
        print("Không có đơn nào" + ("" if args.all else " đang mở (thêm --all để xem tất cả)") + ".")
    for o in sorted(orders, key=lambda o: o.created_at):
        print(f"{o.code}  {o.status:10s} {'+'.join(o.services):8s} {o.pages:4d} tr  {fmt_vnd(o.price_vnd):>12s}  "
              f"đã trả {fmt_vnd(o.paid_vnd):>12s}  {o.customer_email or '(đã xoá)'}  {time.strftime('%d/%m %H:%M', time.localtime(o.updated_at))}"
              + (f"\n      CẦN BẠN: {o.escalation}" if o.escalation and o.status in ('escalated', 'failed') else ""))
    return 0


def cmd_paid(args, state: StateDir) -> int:
    cfg = _load(state)
    ops = _ops_for_cli(state, cfg)
    try:
        order = ops.record_manual_payment(args.code.upper(), amount_vnd=args.amount)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"✓ Đã ghi nhận thanh toán cho đơn {order.code} (trạng thái: {order.status}). AI sẽ xử lý ở nhịp tới.")
    return 0


def cmd_refund(args, state: StateDir) -> int:
    cfg = _load(state)
    ops = _ops_for_cli(state, cfg)
    try:
        order = ops.record_refund(args.code.upper(), memo=args.memo or "")
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"✓ Đã ghi hoàn tiền đơn {order.code} vào sổ cái" + (" và báo khách qua email." if ops.mail else "."))
    return 0


def cmd_prices(args, state: StateDir) -> int:
    from .ops.orders import BUNDLES, expand_services, quote_total
    from .ops.templates import fmt_vnd, price_table
    print(price_table())
    pages = args.pages
    print(f"Ví dụ báo giá cho tài liệu {pages} trang:")
    for code, spec in BUNDLES.items():
        items = expand_services([code])
        print(f"  {spec['name']}: {fmt_vnd(quote_total(items, pages))} (lẻ từng dịch vụ: "
              f"{fmt_vnd(sum(quote_total([s], pages) for s in items))})")
    return 0


def cmd_convert(args, state: StateDir) -> int:
    from .ops.legacy_fonts import convert_docx, convert_plain
    src = Path(args.file)
    if not src.exists():
        sys.exit(f"Không thấy tệp {src}")
    dst = Path(args.output) if args.output else src.with_name(f"UNICODE_{src.name}")
    if src.suffix.lower() == ".docx":
        rep = convert_docx(src, dst)
        print(f"✓ {dst}: chuyển {rep.paragraphs_converted} đoạn (TCVN3: {rep.tcvn3}, VNI: {rep.vni}) sang Unicode"
              if rep.changed else f"Không thấy đoạn nào gõ phông TCVN3/VNI; đã chép nguyên tệp sang {dst}")
    elif src.suffix.lower() == ".txt":
        text, enc = convert_plain(src.read_text(encoding="utf-8", errors="ignore"))
        dst.write_text(text, encoding="utf-8")
        print(f"✓ {dst}: " + (f"chuyển từ {enc.upper()} sang Unicode" if enc else "không thấy chữ TCVN3/VNI, giữ nguyên"))
    else:
        sys.exit("Chỉ chuyển được .docx hoặc .txt (tệp .doc: mở bằng Word, Lưu thành .docx).")
    return 0


def cmd_ads(args, state: StateDir) -> int:
    from decimal import Decimal
    from .ops.templates import fmt_vnd
    cfg = _load(state)
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    if args.ads_cmd == "spend":
        usd = D(Decimal(args.vnd) / Decimal(cfg.vnd_per_usd))
        if usd > ledger.balance("growth"):
            sys.exit(f"Quỹ mở rộng chỉ còn {fmt(ledger.balance('growth'), 2)} USD, không đủ ghi {fmt_vnd(args.vnd)}. "
                     "Quảng cáo chỉ được chi từ Quỹ mở rộng 49%.")
        ledger.growth_spend(usd, "marketing", args.memo or f"Quảng cáo thuê ngoài {fmt_vnd(args.vnd)}",
                            meta={"vnd": args.vnd, "line": args.line, "external": True})
        print(f"✓ Đã ghi chi quảng cáo {fmt_vnd(args.vnd)} vào Quỹ mở rộng 49% (còn {fmt(ledger.balance('growth'), 2)} USD).")
        return 0
    print(f"Quảng cáo tự động: {'BẬT' if cfg.ads_enabled else 'TẮT'} · tài khoản: {cfg.ad_account_id or '(chưa có)'} · "
          f"trần {fmt_vnd(cfg.ads_weekly_cap_vnd)} mỗi {cfg.ads_every_days} ngày · ngách: {', '.join(cfg.ads_lines)}")
    print(f"Tình trạng: {state.kv_get('ads_status', 'chưa chạy') or 'chưa chạy'} · Quỹ mở rộng: {fmt(ledger.balance('growth'), 2)} USD")
    for c in (state.kv_get("ads_campaigns", []) or [])[-10:]:
        print(f"  {time.strftime('%d/%m/%Y', time.localtime(c['ts']))}  {fmt_vnd(c['budget_vnd'])} (+VAT = {fmt_vnd(c['total_vnd'])})  "
              f"chiến dịch {c.get('campaign_id', '?')}  bài {c.get('post', '?')}")
    spent = [e for e in ledger.entries if e.kind == "growth_spend" and e.category == "marketing"]
    print(f"Tổng đã chi quảng cáo từ Quỹ mở rộng: {fmt(sum((-e.amount for e in spent), ZERO), 2)} USD ({len(spent)} lần)")
    return 0


def cmd_demo_ops(args, state: StateDir) -> int:
    from .ops.demo import run_demo
    return run_demo(verbose=not args.quiet)


def _pip_install(req: Path) -> bool:
    import subprocess
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)]
    for extra in ([], ["--user"]):
        if subprocess.run(base + extra).returncode == 0:
            return True
    return False


def _windows_startup_script(run_bat: Path) -> bytes:
    """Tệp .cmd đặt trong thư mục Khởi động: mở AI trong cửa sổ thu nhỏ mỗi lần đăng nhập Windows."""
    return (f'@echo off\r\nchcp 65001 >nul\r\nstart "automaton51" /min "{run_bat}"\r\n').encode("utf-8")


def _launch_agent_plist(repo: Path, python: str, state_dir: Path) -> str:
    """LaunchAgent cho macOS: chạy khi đăng nhập, tự bật lại nếu dừng."""
    from xml.sax.saxutils import escape as x
    args = [python, "-m", "automaton51", "--state", str(state_dir), "run", "--serve"]
    items = "".join(f"\n    <string>{x(a)}</string>" for a in args)
    log = x(str(state_dir / "automaton51.log"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>{items}
  </array>
  <key>WorkingDirectory</key><string>{x(str(repo))}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUTF8</key><string>1</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


LAUNCH_AGENT_LABEL = "vn.automaton51"


def cmd_install(args, state: StateDir) -> int:
    """Cài đặt trọn gói: thư viện -> hỏi thông tin (setup) -> kiểm tra (doctor) -> tự chạy khi bật máy -> chạy ngay."""
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    state_dir = state.root.resolve()
    print("=================== CÀI ĐẶT automaton51 ===================\n")
    print("[1/5] Cài thư viện cần thiết (anthropic)...")
    if not _pip_install(repo / "requirements.txt"):
        sys.exit("✗ Không cài được thư viện. Kiểm tra kết nối Internet rồi chạy lại tệp cài đặt.")
    print("\n[2/5] Thông tin của bạn. Mục nào đã có sẵn thì bấm Enter để giữ nguyên.")
    print("      Khi dán khoá/mật khẩu, màn hình sẽ KHÔNG hiện gì (để bảo mật) — cứ dán (chuột phải hoặc Ctrl+V) rồi Enter.\n")
    ns = argparse.Namespace(email=None, alias=None, alias_tag=None, owner=None, business=None, notify_email=None, bank=None,
                            account=None, account_name=None, payment_provider=None, facebook_page_id=None, seed_usd=None,
                            from_install=True)
    cmd_setup(ns, state)
    print("\n[3/5] Kiểm tra kết nối...\n")
    try:
        doctor_ok = cmd_doctor(argparse.Namespace(offline=False), state) == 0
    except SystemExit:
        doctor_ok = False
    if os.name == "nt":
        run_bat = repo / "deploy" / "chay-tren-windows.bat"
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        print("\n[4/5] Cho AI tự chạy mỗi khi bật máy...")
        try:
            startup.mkdir(parents=True, exist_ok=True)
            (startup / "automaton51.cmd").write_bytes(_windows_startup_script(run_bat))
            print(f"  ✓ Đã thêm vào thư mục Khởi động của Windows ({startup})")
        except OSError as exc:
            print(f"  ✗ Không thêm được ({exc}). Bạn có thể tự bấm đúp {run_bat} sau mỗi lần bật máy.")
        if _ask("  Tắt chế độ ngủ khi cắm sạc để AI chạy liên tục? (C/k)", "C").lower().startswith("c"):
            r = subprocess.run(["powercfg", "/change", "standby-timeout-ac", "0"], capture_output=True)
            print("  ✓ Đã tắt chế độ ngủ khi cắm sạc." if r.returncode == 0 else
                  "  ✗ Không đổi được; vào Settings > System > Power và đặt Sleep = Never.")
        print("\n[5/5] Khởi động AI...")
        if doctor_ok:
            # Chuỗi lệnh (không phải danh sách) để giữ ngoặc kép quanh tiêu đề cửa sổ của lệnh start.
            subprocess.Popen(f'cmd /c start "automaton51" /min "{run_bat}"', cwd=str(repo))
            print("  ✓ AI đang chạy trong một cửa sổ thu nhỏ trên thanh tác vụ. Bảng điều khiển: http://localhost:8451")
        else:
            print("  ! Còn mục chưa đạt ở bước 3. Sửa xong, bấm đúp deploy\\lenh-nhanh-windows.bat, chọn 6 (kiểm tra) rồi 8 (chạy).")
    elif sys.platform == "darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        plist = agents / f"{LAUNCH_AGENT_LABEL}.plist"
        print("\n[4/5] Cho AI tự chạy mỗi khi đăng nhập máy Mac...")
        try:
            agents.mkdir(parents=True, exist_ok=True)
            plist.write_text(_launch_agent_plist(repo, sys.executable, state_dir), encoding="utf-8")
            print(f"  ✓ Đã tạo {plist}")
        except OSError as exc:
            print(f"  ✗ Không tạo được ({exc}).")
        print("  Để máy không ngủ khi cắm sạc: System Settings > Battery (hoặc Energy) > bật 'Prevent automatic sleeping'.")
        print("\n[5/5] Khởi động AI...")
        if doctor_ok and plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            r = subprocess.run(["launchctl", "load", "-w", str(plist)], capture_output=True, text=True)
            print("  ✓ AI đang chạy nền. Bảng điều khiển: http://localhost:8451" if r.returncode == 0 else
                  f"  ✗ launchctl báo lỗi: {r.stderr.strip()}. Chạy tay: {sys.executable} -m automaton51 --state {state_dir} run --serve")
        else:
            print(f"  ! Còn mục chưa đạt ở bước 3. Sửa xong, chạy: {sys.executable} -m automaton51 --state {state_dir} doctor")
    else:
        print("\n[4/5] Tự chạy 24/7 trên máy chủ Linux: xem deploy/README.md (systemd).")
        print(f"[5/5] Chạy ngay: {sys.executable} -m automaton51 --state {state_dir} run --serve   (bảng điều khiển http://localhost:8451)")
    if doctor_ok:
        print("\nXONG. Mỗi sáng bạn nhận một email báo cáo. Chỉ khi có email \"[CẦN BẠN]\" mới phải làm việc "
              "(hoàn tiền cho khách hoặc nạp thêm tiền API).")
    else:
        print("\nCHƯA XONG: sửa các mục có dấu ✗ ở bước 3 (xem mục \"Xử lý sự cố\" trong HUONG-DAN-CAI-DAT.md), rồi chạy lại "
              "tệp cài đặt — mục nào đã đúng chỉ cần bấm Enter.")
    return 0 if doctor_ok else 3

# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="automaton51", description="AI tự kiếm tiền, tự sinh tồn, chia lợi nhuận 51% chủ sở hữu / 49% mở rộng.")
    p.add_argument("--state", default=os.environ.get("AUTOMATON51_STATE", "./state"), help="thư mục trạng thái (mặc định ./state)")
    p.add_argument("--version", action="version", version=f"automaton51 {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="khai sinh tác nhân mới")
    s.add_argument("--name", default="Automaton-51")
    s.add_argument("--owner", help="tên chủ sở hữu")
    s.add_argument("--contact", help="liên hệ hiển thị trên cửa hàng (email/Zalo/website)")
    s.add_argument("--seed-usd", type=_money_arg, default=None, help="vốn mồi ban đầu (USD)")
    s.add_argument("--mode", choices=["sim", "live"], default="sim")
    s.add_argument("--genesis", help="nhiệm vụ khai sinh")
    s.add_argument("--model", help="model cho tầng normal (mặc định claude-opus-5-5)")
    s.add_argument("--port", type=int, default=8451)
    s.add_argument("--playbook", help="tên playbook trong thư mục playbooks/ (xem: automaton51 playbook list)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("playbook", help="liệt kê / áp playbook thị trường ngách cho tác nhân")
    ps = s.add_subparsers(dest="pb_cmd", required=True)
    ps.add_parser("list", help="liệt kê playbook có sẵn")
    ap = ps.add_parser("apply", help="chép playbook vào STRATEGY.md và đặt nhiệm vụ khai sinh")
    ap.add_argument("name")
    s.set_defaults(func=cmd_playbook)

    s = sub.add_parser("run", help="chạy vòng lặp nhịp tim + tác nhân")
    s.add_argument("--ticks", type=int, default=None, help="số nhịp rồi dừng (mặc định chạy mãi)")
    s.add_argument("--serve", action="store_true", help="bật dashboard/webhook cùng lúc")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default="127.0.0.1", help="mặc định chỉ máy này truy cập; dùng 0.0.0.0 khi cần nhận webhook từ ngoài (đặt sau HTTPS)")
    s.add_argument("--mode", choices=["sim", "live"], default=None, help="ghi đè chế độ trong config")
    s.add_argument("--realtime", action="store_true", help="sim nhưng dùng thời gian thật")
    s.add_argument("--no-brain", action="store_true", help="chỉ chạy nhịp tim (không suy nghĩ)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("simulate", help="mô phỏng nhanh, không tốn tiền, không cần API")
    s.add_argument("--ticks", type=int, default=96)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--seed-usd", type=_money_arg, default=D("20"))
    s.add_argument("--name", default="Automaton-51-sim")
    s.add_argument("--fresh", action="store_true", help="dùng thư mục tạm mới")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_simulate)

    sub.add_parser("status", help="tình trạng hiện tại").set_defaults(func=cmd_status)

    s = sub.add_parser("ledger", help="xem sổ cái")
    s.add_argument("--tail", type=int, default=30)
    s.add_argument("--verify", action="store_true", help="kiểm tra chuỗi băm + bất biến")
    s.set_defaults(func=cmd_ledger)

    s = sub.add_parser("revenue", help="ghi/xem doanh thu thật")
    rs = s.add_subparsers(dest="rev_cmd", required=True)
    a = rs.add_parser("add", help="ghi một khoản khách đã trả")
    a.add_argument("amount", type=_money_arg)
    a.add_argument("--memo", default="")
    a.add_argument("--source", default="manual")
    a.add_argument("--product", help="mã sản phẩm (P0001)")
    a.add_argument("--job", help="mã việc (J0001)")
    a.add_argument("--external-id", help="mã giao dịch để chống trùng")
    lst = rs.add_parser("list")
    lst.add_argument("--tail", type=int, default=20)
    s.set_defaults(func=cmd_revenue)

    s = sub.add_parser("fund", help="nạp vốn vào ví vận hành")
    s.add_argument("amount", type=_money_arg)
    s.add_argument("--memo")
    s.set_defaults(func=cmd_fund)

    s = sub.add_parser("payout", help="rút Quỹ chủ sở hữu 51%%")
    s.add_argument("amount", type=_money_arg, nargs="?", default=None)
    s.add_argument("--memo")
    s.set_defaults(func=cmd_payout)

    s = sub.add_parser("withdraw", help="rút vốn khỏi ví vận hành")
    s.add_argument("amount", type=_money_arg)
    s.add_argument("--memo")
    s.set_defaults(func=cmd_withdraw)

    s = sub.add_parser("send", help="nhắn cho tác nhân (đọc ở lượt sau)")
    s.add_argument("message")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("serve", help="chỉ chạy dashboard/webhook")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(func=cmd_serve)

    sub.add_parser("seal", help="niêm phong hiến pháp + mô-đun bảo vệ (chủ sở hữu)").set_defaults(func=cmd_seal)
    sub.add_parser("verify", help="kiểm tra niêm phong").set_defaults(func=cmd_verify)
    sub.add_parser("children", help="liệt kê tác nhân con").set_defaults(func=cmd_children)
    sub.add_parser("stop", help="bật công tắc tắt nguồn (kill switch)").set_defaults(func=cmd_stop)
    sub.add_parser("resume", help="tắt công tắc STOP").set_defaults(func=cmd_resume)
    sub.add_parser("resurrect", help="hồi sinh sau khi nạp vốn").set_defaults(func=cmd_resurrect)

    s = sub.add_parser("setup", help="cài đặt vận hành tự động một lần (tài khoản nhận tiền + khoá kết nối)")
    s.add_argument("--email", help="Gmail dùng cho kinh doanh")
    s.add_argument("--alias", help="địa chỉ nhận khách (mặc định: <gmail>+hocthuat@gmail.com)")
    s.add_argument("--alias-tag", help="phần sau dấu + (mặc định hocthuat)")
    s.add_argument("--owner", help="tên ký trong thư")
    s.add_argument("--business", help="tên dịch vụ")
    s.add_argument("--notify-email", help="email nhận báo cáo hằng ngày")
    s.add_argument("--bank", help="ngân hàng: vcb, tcb, mbbank, acb, bidv, vietinbank... hoặc BIN 6 số")
    s.add_argument("--account", help="số tài khoản nhận tiền")
    s.add_argument("--account-name", help="tên chủ tài khoản")
    s.add_argument("--payment-provider", choices=["sepay", "webhook"])
    s.add_argument("--facebook-page-id")
    s.add_argument("--address", default=None, help="địa chỉ liên hệ in trong thư quảng cáo")
    s.add_argument("--website", default=None, help="địa chỉ Trang Facebook / website")
    s.add_argument("--phone", default=None, help="số điện thoại RIÊNG cho kinh doanh (không dùng số cá nhân)")
    s.add_argument("--ad-account", default=None, help="số tài khoản quảng cáo Meta (bật quảng cáo nếu có token)")
    s.add_argument("--seed-usd", type=_money_arg, default=None, help="vốn mồi USD nếu sổ cái đang trống")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("doctor", help="kiểm tra mọi kết nối (Anthropic, Gmail, SePay, Facebook)")
    s.add_argument("--offline", action="store_true", help="chỉ kiểm tra cấu hình, không gọi mạng")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("outreach", help="danh bạ: nhập CSV từ Google Contacts, xem thống kê")
    os_ = s.add_subparsers(dest="out_cmd", required=True)
    imp = os_.add_parser("import", help="nhập CSV xuất từ contacts.google.com")
    imp.add_argument("csv")
    os_.add_parser("status")
    s.set_defaults(func=cmd_outreach)

    s = sub.add_parser("orders", help="xem đơn hàng")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_orders)

    s = sub.add_parser("paid", help="xác nhận khoản tiền khách chuyển thiếu mã đơn là của đơn này")
    s.add_argument("code")
    s.add_argument("--amount", type=int, default=None, help="số đồng (chỉ cần khi hệ thống chưa thấy giao dịch)")
    s.set_defaults(func=cmd_paid)

    s = sub.add_parser("refund", help="ghi sổ sau khi BẠN đã chuyển tiền hoàn cho khách")
    s.add_argument("code")
    s.add_argument("--memo")
    s.set_defaults(func=cmd_refund)

    sub.add_parser("install", help="cài đặt trọn gói: thư viện, thông tin, kiểm tra, tự chạy khi bật máy").set_defaults(func=cmd_install)

    s = sub.add_parser("prices", help="bảng giá hai ngách và ví dụ báo giá gói")
    s.add_argument("--pages", type=int, default=180)
    s.set_defaults(func=cmd_prices)

    s = sub.add_parser("convert", help="chuyển tệp gõ phông TCVN3/VNI (.VnTime) sang Unicode, làm tại máy")
    s.add_argument("file")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("ads", help="quảng cáo: xem tình trạng, ghi khoản chi quảng cáo thuê ngoài (trích Quỹ mở rộng 49%%)")
    ads_sub = s.add_subparsers(dest="ads_cmd", required=True)
    ads_sub.add_parser("status")
    sp = ads_sub.add_parser("spend", help="ghi khoản đã trả cho quảng cáo/agency (đồng, đã gồm thuế)")
    sp.add_argument("vnd", type=int)
    sp.add_argument("--memo")
    sp.add_argument("--line", choices=["A", "B"], default="A")
    s.set_defaults(func=cmd_ads)

    s = sub.add_parser("demo-ops", help="chạy thử trọn luồng tự động bằng dữ liệu giả (không cần khoá, không tốn tiền)")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_demo_ops)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # màn hình Windows cũ: ký tự không in được thành "?" thay vì làm sập chương trình
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    state = StateDir(args.state)
    load_dotenv(state.root / ".env")
    return int(args.func(args, state) or 0)
