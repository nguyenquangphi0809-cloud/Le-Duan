"""Nhân bản: tạo tác nhân con có ví riêng, vốn mồi lấy từ Quỹ mở rộng 49% của mẹ.

Con thừa hưởng: hiến pháp (cùng mã nguồn niêm phong), điều lệ 51/49, chủ sở hữu.
Con là thực thể độc lập: ví riêng, sổ cái riêng, áp lực sinh tồn riêng.
"""
from __future__ import annotations

import secrets
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .catalog import slugify
from .config import Config
from .ledger import Ledger
from .money import D
from .state import StateDir, file_lock


def _children_records(state: StateDir) -> list[dict[str, Any]]:
    return state.read_json(state.children_path, []) or []


def spawn_child(parent_state: StateDir, parent_cfg: Config, parent_ledger: Ledger, name: str, seed,
                genesis: str, now: float | None = None, clock=None) -> dict[str, Any]:
    now = float(now if now is not None else time.time())
    seed = D(seed)
    records = _children_records(parent_state)
    slug = slugify(name)
    if any(r["slug"] == slug for r in records) or (parent_state.children_dir / slug).exists():
        slug = f"{slug}-{len(records) + 1}"
    child_dir = parent_state.children_dir / slug
    child_state = StateDir(child_dir).ensure()

    child_cfg = Config.from_dict(parent_cfg.to_dict())
    child_cfg.name = name
    child_cfg.genesis_prompt = genesis
    child_cfg.parent_name = parent_cfg.name
    child_cfg.lineage = list(parent_cfg.lineage) + [parent_cfg.name]
    child_cfg.revenue_webhook_secret = secrets.token_hex(16)
    child_cfg.dashboard_port = parent_cfg.dashboard_port + len(records) + 1
    child_cfg.auto_start_children = False
    child_cfg.sim_seed = parent_cfg.sim_seed + len(records) + 1
    child_cfg.save(child_state.config_path)

    # Mẹ chi từ quỹ mở rộng (raise nếu không đủ) -> con nhận vốn mồi
    parent_ledger.growth_spend(seed, "replication", memo=f"Vốn mồi cho tác nhân con '{name}'",
                               meta={"child": slug, "child_path": str(child_dir)})
    child_ledger = Ledger(child_state.ledger_path, clock=clock, lock_path=child_state.lock_path)
    child_ledger.deposit(seed, memo=f"Vốn mồi từ mẹ '{parent_cfg.name}' (Quỹ mở rộng 49%)",
                         meta={"parent": parent_cfg.name})
    child_ledger.note("birth", f"Khai sinh tác nhân con '{name}', thế hệ {len(child_cfg.lineage)}")
    child_state.kv_set("born_at", now)
    child_state.strategy_path.write_text(f"Nhiệm vụ khai sinh từ mẹ: {genesis}\n", encoding="utf-8")

    record = {"name": name, "slug": slug, "path": str(child_dir), "seed": f"{seed:f}", "spawned_at": now,
              "generation": len(child_cfg.lineage), "pid": None}
    if parent_cfg.auto_start_children and parent_cfg.mode == "live":
        try:
            proc = subprocess.Popen([sys.executable, "-m", "automaton51", "--state", str(child_dir), "run"],  # noqa: S603
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            record["pid"] = proc.pid
        except OSError as exc:
            record["start_error"] = str(exc)
    with file_lock(parent_state.lock_path):
        records = _children_records(parent_state)
        records.append(record)
        parent_state.write_json(parent_state.children_path, records)
    return record


def list_children(state: StateDir) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in _children_records(state):
        info = dict(r)
        child = StateDir(Path(r["path"]))
        status = child.read_json(child.status_path, {}) or {}
        info["alive"] = status.get("alive")
        info["tier"] = status.get("tier")
        info["balances"] = status.get("balances")
        info["owner_received"] = (status.get("totals") or {}).get("owner_received")
        out.append(info)
    return out
