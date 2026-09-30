from __future__ import annotations

import tempfile
from pathlib import Path

from automaton51.config import Config
from automaton51.ledger import Ledger
from automaton51.state import StateDir


def make_state(seed_usd: str = "20", **cfg_overrides) -> tuple[StateDir, Config]:
    root = Path(tempfile.mkdtemp(prefix="a51-test-"))
    state = StateDir(root).ensure()
    cfg = Config(name="Test-51", mode="sim", owner_name="Chủ test", revenue_webhook_secret="s3cret", **cfg_overrides)
    cfg.save(state.config_path)
    if seed_usd and float(seed_usd) > 0:
        Ledger(state.ledger_path, lock_path=state.lock_path).deposit(seed_usd, memo="seed")
    return state, cfg
