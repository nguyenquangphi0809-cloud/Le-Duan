"""Thư mục trạng thái của một tác nhân (mỗi tác nhân/con một thư mục riêng)."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Khoá liên tiến trình (flock). Trên hệ không có fcntl thì bỏ qua."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StateDir:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()

    # ---- đường dẫn ----
    @property
    def config_path(self) -> Path: return self.root / "config.json"
    @property
    def ledger_path(self) -> Path: return self.root / "ledger.jsonl"
    @property
    def status_path(self) -> Path: return self.root / "status.json"
    @property
    def journal_path(self) -> Path: return self.root / "journal.md"
    @property
    def strategy_path(self) -> Path: return self.root / "STRATEGY.md"
    @property
    def catalog_path(self) -> Path: return self.root / "catalog.json"
    @property
    def kv_path(self) -> Path: return self.root / "kv.json"
    @property
    def revenue_inbox_path(self) -> Path: return self.root / "revenue_inbox.jsonl"
    @property
    def owner_inbox_path(self) -> Path: return self.root / "owner_inbox.jsonl"
    @property
    def funding_requests_path(self) -> Path: return self.root / "funding_requests.jsonl"
    @property
    def children_path(self) -> Path: return self.root / "children.json"
    @property
    def turns_path(self) -> Path: return self.root / "turns.jsonl"
    @property
    def workspace(self) -> Path: return self.root / "workspace"
    @property
    def products_dir(self) -> Path: return self.workspace / "products"
    @property
    def content_dir(self) -> Path: return self.workspace / "content"
    @property
    def outbox_dir(self) -> Path: return self.workspace / "outbox"
    @property
    def children_dir(self) -> Path: return self.root / "children"
    @property
    def lock_path(self) -> Path: return self.root / ".lock"
    @property
    def pid_path(self) -> Path: return self.root / "run.pid"
    @property
    def kill_switch_path(self) -> Path: return self.root / "STOP"

    def ensure(self) -> "StateDir":
        for d in (self.root, self.workspace, self.products_dir, self.content_dir,
                  self.outbox_dir, self.children_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def exists(self) -> bool:
        return self.config_path.exists()

    # ---- JSON / JSONL ----
    def read_json(self, path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except json.JSONDecodeError:
            return default

    def write_json(self, path: Path, obj: Any) -> None:
        atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str))

    def append_jsonl(self, path: Path, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False, default=str)
        with file_lock(self.lock_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        out.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return out

    # ---- KV nhỏ ----
    def kv_get(self, key: str, default: Any = None) -> Any:
        return (self.read_json(self.kv_path, {}) or {}).get(key, default)

    def kv_set(self, key: str, value: Any) -> None:
        with file_lock(self.lock_path):
            data = self.read_json(self.kv_path, {}) or {}
            data[key] = value
            self.write_json(self.kv_path, data)

    # ---- tiến trình chạy ----
    def claim_process(self) -> None:
        """Ghi PID; từ chối nếu một tiến trình khác còn sống đang chạy thư mục này."""
        if self.pid_path.exists():
            try:
                other = int(self.pid_path.read_text().strip() or "0")
            except ValueError:
                other = 0
            if other and other != os.getpid() and _pid_alive(other):
                raise RuntimeError(
                    f"Một tiến trình khác (PID {other}) đang chạy tác nhân này. "
                    f"Dừng nó trước, hoặc xoá {self.pid_path} nếu chắc chắn nó đã chết."
                )
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def release_process(self) -> None:
        try:
            if self.pid_path.exists() and self.pid_path.read_text().strip() == str(os.getpid()):
                self.pid_path.unlink()
        except OSError:
            pass

    def kill_switch_engaged(self) -> bool:
        return self.kill_switch_path.exists()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
