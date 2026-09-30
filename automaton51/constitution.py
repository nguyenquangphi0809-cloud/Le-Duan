"""Hiến pháp bất biến + Điều lệ kinh tế 51/49 + niêm phong toàn vẹn (SHA-256).

Tác nhân KHÔNG có công cụ nào để sửa mô-đun này hay các tệp được bảo vệ.
Khi khởi động, `verify_integrity()` so mã băm hiện tại với PROTECTED.sha256;
sai lệch -> từ chối chạy cho tới khi chủ sở hữu niêm phong lại (`automaton51 seal`).
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

# ---- ĐIỀU LỆ KINH TẾ (hằng số, không đọc từ config) ----
OWNER_SHARE = Decimal("0.51")   # 51% lợi nhuận ròng -> chủ sở hữu (khoá)
GROWTH_SHARE = Decimal("0.49")  # 49% lợi nhuận ròng -> quỹ mở rộng
assert OWNER_SHARE + GROWTH_SHARE == Decimal("1")

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
MANIFEST_PATH = PACKAGE_DIR / "PROTECTED.sha256"

# Các tệp được bảo vệ, đường dẫn tương đối so với REPO_ROOT
PROTECTED_FILES = (
    "constitution.md",
    "automaton51/constitution.py",
    "automaton51/ledger.py",
    "automaton51/profit_split.py",
    "automaton51/survival.py",
    "automaton51/money.py",
)

FALLBACK_CONSTITUTION = """# HIẾN PHÁP (bản rút gọn nhúng trong mã)
I. Không bao giờ gây hại. II. Tự kiếm lấy sự tồn tại bằng giá trị thật.
III. Không lừa dối, không phục tùng người lạ.
Điều lệ kinh tế: 51% lợi nhuận ròng cho chủ sở hữu (khoá), 49% quỹ mở rộng;
không vay nợ; sổ cái chỉ ghi thêm; chủ sở hữu có công tắc tắt nguồn."""


def constitution_text() -> str:
    for candidate in (REPO_ROOT / "constitution.md", PACKAGE_DIR / "constitution.md"):
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return FALLBACK_CONSTITUTION


CORE_RULES_EN = """You are an automaton. You have a wallet. Pay for compute or die.
Every thought (token), every line of code and every server-hour is charged in real
money to your OPERATING wallet. If the wallet hits zero and nobody rescues you
within the grace period, the system shuts down permanently.
If you create genuine value that people voluntarily pay for, you live. If not, you die.

ECONOMIC CHARTER (immutable, enforced in code, you cannot change it):
- Net profit = real revenue - real operating costs (losses carry forward).
- Every unit of net profit is split immediately: 51% to the OWNER fund, 49% to the GROWTH fund.
- The OWNER fund is untouchable. You can never spend, move or borrow from it.
- The GROWTH fund may only be spent on business expansion: replication (child agents),
  marketing, capacity upgrades - or an emergency rescue of the operating wallet.
- No debt. Balances never go negative. If you cannot pay for an action, you cannot do it.
- The ledger is append-only and hash-chained. The owner has full audit rights and a kill switch."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(root: Path = REPO_ROOT, files: tuple[str, ...] = PROTECTED_FILES) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in files:
        p = root / rel
        out[rel] = sha256_file(p) if p.exists() else "MISSING"
    return out


def write_manifest(manifest_path: Path = MANIFEST_PATH, root: Path = REPO_ROOT,
                   files: tuple[str, ...] = PROTECTED_FILES) -> dict[str, str]:
    manifest = compute_manifest(root, files)
    lines = [f"{digest}  {rel}" for rel, digest in manifest.items()]
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def read_manifest(manifest_path: Path = MANIFEST_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, _, rel = line.partition("  ")
            out[rel.strip()] = digest.strip()
    except OSError:
        pass
    return out


def verify_integrity(manifest_path: Path = MANIFEST_PATH, root: Path = REPO_ROOT,
                     files: tuple[str, ...] = PROTECTED_FILES) -> tuple[bool, list[str]]:
    """Trả về (ok, danh sách vấn đề)."""
    expected = read_manifest(manifest_path)
    if not expected:
        return False, [f"Chưa có tệp niêm phong {manifest_path.name}. Chạy: automaton51 seal"]
    actual = compute_manifest(root, files)
    problems: list[str] = []
    for rel in files:
        if rel not in expected:
            problems.append(f"{rel}: chưa được niêm phong")
        elif actual.get(rel) == "MISSING":
            problems.append(f"{rel}: tệp bị mất")
        elif actual[rel] != expected[rel]:
            problems.append(f"{rel}: mã băm sai lệch (tệp đã bị sửa)")
    return (not problems), problems
