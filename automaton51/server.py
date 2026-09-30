"""Dashboard + cửa hàng + webhook doanh thu (thư viện chuẩn, không phụ thuộc ngoài).

  GET  /                 dashboard: ví, tầng, chia 51/49, sổ cái, sản phẩm, con
  GET  /store            cửa hàng: các sản phẩm đang bán (chia sẻ link này cho khách)
  GET  /api/status       JSON trạng thái
  GET  /api/ledger?tail=50
  POST /webhook/revenue  {amount, currency?, memo?, source?, external_id?, product_id?, job_id?}
                         header X-Automaton-Secret: <revenue_webhook_secret>
"""
from __future__ import annotations

import hmac
import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Config
from .ledger import Ledger
from .money import D, fmt
from .revenue import RevenueInbox
from .state import StateDir


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: StateDir, cfg: Config):
        super().__init__(address, Handler)
        self.state = state
        self.cfg = cfg


class Handler(BaseHTTPRequestHandler):
    server: DashboardServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # im lặng

    # ---- tiện ích ----
    def _send(self, code: int, body: str | bytes, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str), "application/json; charset=utf-8")

    def _status(self) -> dict[str, Any]:
        return self.server.state.read_json(self.server.state.status_path, {}) or {}

    # ---- GET ----
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, render_dashboard(self.server.state, self.server.cfg, self._status()))
        elif url.path == "/store":
            self._send(200, render_store(self.server.state, self.server.cfg))
        elif url.path == "/api/status":
            self._json(200, self._status())
        elif url.path == "/api/ledger":
            tail = int((parse_qs(url.query).get("tail") or ["50"])[0])
            ledger = Ledger(self.server.state.ledger_path, lock_path=self.server.state.lock_path)
            self._json(200, [json.loads(e.to_json()) for e in ledger.tail(tail)])
        elif url.path == "/health":
            self._json(200, {"ok": True, "ts": time.time()})
        else:
            self._send(404, "<h1>404</h1>")

    # ---- POST ----
    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/webhook/revenue":
            self._json(404, {"error": "not found"})
            return
        secret = self.server.cfg.revenue_webhook_secret
        given = self.headers.get("X-Automaton-Secret") or (parse_qs(url.query).get("secret") or [""])[0]
        if not secret or not hmac.compare_digest(str(given), secret):
            self._json(401, {"error": "sai secret"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            amount = D(payload.get("amount"))
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"error": f"JSON không hợp lệ: {exc}"})
            return
        if amount <= 0:
            self._json(400, {"error": "amount phải > 0"})
            return
        inbox = RevenueInbox(self.server.state)
        try:
            ev = inbox.append(amount, source=str(payload.get("source") or "webhook"), memo=str(payload.get("memo") or "")[:300],
                              currency=str(payload.get("currency") or "USD"), external_id=str(payload.get("external_id") or "")[:100],
                              product_id=str(payload.get("product_id") or ""), job_id=str(payload.get("job_id") or ""))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(200, {"ok": True, "duplicate": ev is None, "id": ev.id if ev else None})


# ----------------------------------------------------------------------------- render
CSS = """
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px;color:#f5a623}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:#181b22;border:1px solid #262a33;border-radius:10px;padding:14px}
.big{font-size:24px;font-weight:700}.muted{color:#9aa0aa;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:6px 8px;border-bottom:1px solid #262a33;text-align:left;vertical-align:top}
.tier-normal{color:#5ad17a}.tier-low_compute{color:#f5a623}.tier-critical{color:#ff6b6b}.tier-dead{color:#888}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#262a33;font-size:12px}
a{color:#7cc4ff}
"""


def _esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _money(x: Any, places: int = 2) -> str:
    try:
        return fmt(x, places)
    except Exception:  # noqa: BLE001
        return "-"


def render_dashboard(state: StateDir, cfg: Config, st: dict[str, Any]) -> str:
    b = st.get("balances") or {}
    t = st.get("totals") or {}
    tier = st.get("tier", "?")
    ledger = Ledger(state.ledger_path, lock_path=state.lock_path)
    rows = "".join(
        f"<tr><td>{e.seq}</td><td>{time.strftime('%m-%d %H:%M', time.gmtime(e.ts))}</td><td>{_esc(e.kind)}</td>"
        f"<td>{_esc(e.account)}</td><td style='text-align:right'>{'+' if e.amount >= 0 else ''}{_esc(f'{e.amount:.4f}')}</td>"
        f"<td>{_esc(e.category)}</td><td>{_esc(e.memo[:90])}</td></tr>"
        for e in reversed(ledger.tail(40)))
    products = (state.read_json(state.catalog_path, {}) or {}).get("products", {})
    prows = "".join(
        f"<tr><td>{_esc(p['id'])}</td><td>{_esc(p['name'])}</td><td><span class='pill'>{_esc(p['status'])}</span></td>"
        f"<td>{_money(p['price'])}</td><td>{_esc(p.get('sales', 0))}</td><td>{_money(p.get('revenue', 0))}</td></tr>"
        for p in list(products.values())[-20:])
    children = st.get("children") or []
    crows = "".join(
        f"<tr><td>{_esc(c.get('name'))}</td><td>{_esc(c.get('tier') or '?')}</td><td>{_money(c.get('seed'))}</td>"
        f"<td>{_money((c.get('balances') or {}).get('operating', 0))}</td><td>{_money(c.get('owner_received') or 0)}</td></tr>"
        for c in children)
    funding = st.get("funding_requests_pending") or []
    frows = "".join(f"<li>{_money(r.get('amount'))} — {_esc(r.get('reason'))} <span class='muted'>(automaton51 fund {_esc(D(r.get('amount', 0)).quantize(D('0.01')))})</span></li>" for r in funding)
    last = st.get("last_tick") or {}
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(cfg.name)} — automaton51</title><meta http-equiv="refresh" content="30"><style>{CSS}</style></head><body><main>
<h1>{_esc(cfg.name)} <span class="pill">{_esc(cfg.mode)}</span> <span class="pill tier-{_esc(tier)}">{'CÒN SỐNG' if st.get('alive', True) else 'ĐÃ CHẾT'} · {_esc(tier)}</span>{' <span class="pill">STOP</span>' if state.kill_switch_engaged() else ''}</h1>
<div class="muted">Nhịp {_esc(st.get('tick', 0))} · sống {_esc(st.get('uptime_days', 0))} ngày · model {_esc(st.get('model'))} · cập nhật {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(float(st.get('updated_at') or time.time())))} · <a href="/store">Cửa hàng</a> · <a href="/api/status">JSON</a></div>
<h2>Ba ví</h2><div class="grid">
<div class="card"><div class="muted">Ví vận hành (trả chi phí, nhận doanh thu)</div><div class="big">{_money(b.get('operating', 0), 4)}</div><div class="muted">đốt/ngày {_money(st.get('burn_per_day', 0), 4)} · runway {('∞' if st.get('runway_days') is None else f"{float(st.get('runway_days')):.1f} ngày")}</div></div>
<div class="card"><div class="muted">Quỹ CHỦ SỞ HỮU · 51% · khoá</div><div class="big">{_money(b.get('owner', 0), 4)}</div><div class="muted">đã nhận tổng {_money(t.get('owner_received', 0), 4)} · đã rút {_money(t.get('owner_paid_out', 0))}</div></div>
<div class="card"><div class="muted">Quỹ MỞ RỘNG · 49%</div><div class="big">{_money(b.get('growth', 0), 4)}</div><div class="muted">đã nhận {_money(t.get('growth_received', 0), 4)} · đã chi {_money(t.get('growth_spent', 0))} · cứu sinh {_money(t.get('rescued', 0))}</div></div>
</div>
<h2>Kinh tế</h2><div class="grid">
<div class="card"><div class="muted">Tổng doanh thu</div><div class="big">{_money(t.get('revenue', 0))}</div></div>
<div class="card"><div class="muted">Tổng chi phí vận hành</div><div class="big">{_money(t.get('operating_costs', 0), 4)}</div><div class="muted">suy luận {_money(t.get('inference_costs', 0), 4)} · server {_money(t.get('server_costs', 0), 4)}</div></div>
<div class="card"><div class="muted">Lợi nhuận đã chia 51/49</div><div class="big">{_money(t.get('distributed', 0), 4)}</div><div class="muted">chưa chia {_money(st.get('unsettled_profit', 0), 4)}</div></div>
<div class="card"><div class="muted">Nhịp gần nhất</div><div class="big">{'+' + _money(last.get('revenue_in', 0)) if last else '-'}</div><div class="muted">chi suy luận {_money(last.get('inference_cost', 0), 4)} · server {_money(last.get('server_cost', 0), 4)} · {_esc('; '.join(last.get('events') or []))[:160]}</div></div>
</div>
{('<h2>Yêu cầu nạp vốn đang chờ</h2><ul>' + frows + '</ul>') if funding else ''}
<h2>Sản phẩm</h2><table><tr><th>ID</th><th>Tên</th><th>Trạng thái</th><th>Giá</th><th>Đã bán</th><th>Doanh thu</th></tr>{prows or '<tr><td colspan=6 class=muted>chưa có</td></tr>'}</table>
<h2>Tác nhân con</h2><table><tr><th>Tên</th><th>Tầng</th><th>Vốn mồi</th><th>Ví vận hành</th><th>Đã trả chủ</th></tr>{crows or '<tr><td colspan=5 class=muted>chưa nhân bản</td></tr>'}</table>
<h2>Sổ cái (40 dòng mới nhất)</h2><table><tr><th>#</th><th>Lúc</th><th>Loại</th><th>Ví</th><th>Số tiền</th><th>Mục</th><th>Ghi chú</th></tr>{rows}</table>
<p class="muted">Sổ cái chỉ ghi thêm, nối băm SHA-256. Kiểm tra: <code>automaton51 ledger --verify</code></p>
</main></body></html>"""


def render_store(state: StateDir, cfg: Config) -> str:
    products = (state.read_json(state.catalog_path, {}) or {}).get("products", {})
    listed = [p for p in products.values() if p.get("status") == "listed"]
    contact = cfg.owner_contact or "liên hệ chủ cửa hàng"
    cards = "".join(
        f"<div class='card'><h3>{_esc(p['name'])}</h3><div class='muted'>{_esc(p['kind'])} · {_esc(p['id'])}</div>"
        f"<p>{_esc(p['description'][:600])}</p><div class='big'>{_money(p['price'])}</div>"
        f"<p class='muted'>Mua: {_esc(contact)} · tệp: {len(p.get('files') or [])}</p></div>" for p in listed)
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cửa hàng — {_esc(cfg.name)}</title><style>{CSS}</style></head><body><main>
<h1>Cửa hàng của {_esc(cfg.name)}</h1><div class="muted">Sản phẩm số do AI tự trị tạo ra. Thanh toán/giao hàng qua chủ sở hữu: {_esc(contact)} · <a href="/">dashboard</a></div>
<div class="grid" style="margin-top:16px">{cards or '<div class=card><div class=muted>Chưa có sản phẩm đang bán.</div></div>'}</div>
</main></body></html>"""


def start_background(state: StateDir, cfg: Config, port: int | None = None, host: str = "0.0.0.0") -> tuple[DashboardServer, threading.Thread]:
    server = DashboardServer((host, port or cfg.dashboard_port), state, cfg)
    thread = threading.Thread(target=server.serve_forever, name="automaton51-dashboard", daemon=True)
    thread.start()
    return server, thread


def serve_forever(state: StateDir, cfg: Config, port: int | None = None, host: str = "0.0.0.0") -> None:
    server = DashboardServer((host, port or cfg.dashboard_port), state, cfg)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()
