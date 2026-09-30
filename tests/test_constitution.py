import tempfile
import unittest
from pathlib import Path

from automaton51 import constitution as c


class IntegrityTests(unittest.TestCase):
    def test_seal_and_verify(self):
        root = Path(tempfile.mkdtemp())
        (root / "pkg").mkdir()
        (root / "constitution.md").write_text("laws", encoding="utf-8")
        (root / "pkg" / "ledger.py").write_text("code", encoding="utf-8")
        files = ("constitution.md", "pkg/ledger.py")
        manifest = root / "PROTECTED.sha256"
        ok, problems = c.verify_integrity(manifest, root, files)
        self.assertFalse(ok)
        c.write_manifest(manifest, root, files)
        ok, problems = c.verify_integrity(manifest, root, files)
        self.assertTrue(ok, problems)
        (root / "pkg" / "ledger.py").write_text("code # sửa tỷ lệ", encoding="utf-8")
        ok, problems = c.verify_integrity(manifest, root, files)
        self.assertFalse(ok)
        self.assertTrue(any("ledger.py" in p for p in problems))

    def test_repo_is_sealed(self):
        ok, problems = c.verify_integrity()
        self.assertTrue(ok, problems)

    def test_constitution_text_mentions_51_49(self):
        text = c.constitution_text()
        self.assertIn("51", text)
        self.assertIn("49", text)


if __name__ == "__main__":
    unittest.main()
