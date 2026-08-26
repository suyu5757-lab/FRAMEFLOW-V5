from __future__ import annotations

import re
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "git" / "frameflow_safe_sync.ps1"


class SafeSyncStaticTests(unittest.TestCase):
    def test_script_exists_and_uses_current_branch(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"branch", "--show-current"', source)
        self.assertIn('"push", $Remote, $currentBranch', source)
        self.assertIn("currentBranch", source)
        self.assertIn("Write-SyncLog", source)

    def test_script_contains_no_destructive_git_operation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8").lower()
        forbidden = (
            "reset --hard",
            "checkout .",
            "restore .",
            "clean -fd",
            "push --force",
            "push -f",
        )
        for token in forbidden:
            self.assertNotIn(token, source)
        self.assertIsNone(re.search(r"git\s+(merge|rebase|reset|restore|checkout|clean)\b", source))
        self.assertIsNone(re.search(r"git\s+push\s+(?:[^\r\n]+\s+)?(?:main|master)\b", source))

    def test_script_has_abort_markers_and_protected_path_checks(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply"):
            self.assertIn(marker, source)
        self.assertIn("--diff-filter=U", source)
        self.assertIn("protected", source.lower())
        self.assertIn("NO_CHANGES", source)
        self.assertIn("[REDACTED]", source)


if __name__ == "__main__":
    unittest.main()
