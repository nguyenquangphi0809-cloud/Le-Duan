"""Thư mục trạng thái của một tác nhân (mỗi tác nhân/con một thư mục riêng)."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import time as _time

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
try:  # Windows
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Khoá liên tiến trình: flock trên Linux/Mac, msvcrt.locking trên Windows."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    locked_win = False
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - chỉ chạy trên Windows
            fh.seek(0)
            for _ in range(600):
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    locked_win = True
                    break
                except OSError:
                    _time.sleep(0.05)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        elif locked_win:  # pragma: no cover
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        fh.close()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: tệp đích đang được mở (vd bảng điều khiển đang đọc)
                if attempt == 49:
                    raise
                _time.sleep(0.1)
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
    @property
    def restart_path(self) -> Path: return self.root / "RESTART"

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
            if other and other != os.getpid() and _pid_alive(other) and not self._pid_reused(other):
                raise RuntimeError(
                    f"Một tiến trình khác (PID {other}) đang chạy tác nhân này. "
                    f"Dừng nó trước, hoặc xoá {self.pid_path} nếu chắc chắn nó đã chết."
                )
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        self.consume_restart_request()  # yêu cầu cũ (nếu có) đã được đáp ứng bởi chính lần khởi động này

    def running_pid(self) -> "int | None":
        """PID của tiến trình đang chạy thư mục này (None nếu không có)."""
        try:
            pid = int(self.pid_path.read_text().strip() or "0")
        except (OSError, ValueError):
            return None
        if pid and _pid_alive(pid) and not self._pid_reused(pid):
            return pid
        return None

    def request_restart(self) -> None:
        """Nhờ tiến trình đang chạy tự thoát ở nhịp tới; trình bao (.bat/systemd/launchd) sẽ bật lại với cấu hình mới."""
        self.ensure()
        self.restart_path.write_text(str(_time.time()), encoding="utf-8")

    def consume_restart_request(self) -> bool:
        if not self.restart_path.exists():
            return False
        try:
            self.restart_path.unlink()
        except OSError:
            pass
        return True

    def _pid_reused(self, pid: int) -> bool:
        """PID trong tệp đã thuộc về tiến trình KHÁC (vd sau khi khởi động lại máy, Windows cấp lại số PID cũ)?

        Tiến trình chủ luôn được tạo TRƯỚC khi ghi tệp PID; tiến trình tạo SAU thời điểm ghi tệp thì không phải nó.
        """
        started = _process_start_time(pid)
        if started is None:
            return False
        try:
            written = self.pid_path.stat().st_mtime
        except OSError:
            return False
        return started > written + 2.0

    def release_process(self) -> None:
        try:
            if self.pid_path.exists() and self.pid_path.read_text().strip() == str(os.getpid()):
                self.pid_path.unlink()
        except OSError:
            pass

    def kill_switch_engaged(self) -> bool:
        return self.kill_switch_path.exists()


def _win_open_process(pid: int):  # pragma: no cover - chỉ chạy trên Windows
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    return k, handle, ctypes.get_last_error()


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":  # pragma: no cover - Windows: os.kill(pid, 0) sẽ TẮT tiến trình, không được dùng
        import ctypes
        from ctypes import wintypes
        k, handle, err = _win_open_process(pid)
        if not handle:
            return err == 5  # ERROR_ACCESS_DENIED: tiến trình có tồn tại nhưng thuộc người dùng khác
        try:
            code = wintypes.DWORD()
            ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_start_time(pid: int) -> "float | None":
    """Thời điểm (giây epoch) tiến trình được tạo; None nếu không xác định được."""
    if os.name == "nt":  # pragma: no cover - Windows
        import ctypes
        from ctypes import wintypes
        k, handle, _ = _win_open_process(pid)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return created / 1e7 - 11644473600  # FILETIME (100ns từ 1601) -> epoch
        finally:
            k.CloseHandle(handle)
    try:  # Linux: /proc chính xác tới 1/100 giây
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
        ticks = int(raw[raw.rindex(")") + 2:].split()[19])  # trường 22: starttime
        with open("/proc/stat", encoding="utf-8") as fh:
            btime = next(int(line.split()[1]) for line in fh if line.startswith("btime"))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        pass
    try:  # macOS/BSD: thời gian đã chạy dạng [[dd-]hh:]mm:ss
        import subprocess
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(int(pid))], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if not out:
            return None
        days, _, rest = out.rpartition("-")
        secs = 0
        for part in rest.split(":"):
            secs = secs * 60 + int(part)
        return _time.time() - secs - (int(days) * 86400 if days else 0)
    except (OSError, ValueError, Exception):  # noqa: BLE001
        return None
