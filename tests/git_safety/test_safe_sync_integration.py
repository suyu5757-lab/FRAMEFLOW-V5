from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "git" / "frameflow_safe_sync.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh") or "powershell.exe"
SKILL_ROOT = Path(r"D:\11067\CodexHome\skills")
SKILL_TAG = "frameflow-skills-baseline-20260826"
SKILL_CONTRACT = "video-character-design-director/scripts/character_asset_check.py"


def run_command(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed ({result.returncode}): {args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


class SafeSyncFixtureTests(unittest.TestCase):
    """G1-G5 run only against disposable repositories and a bare remote."""

    def make_fixture(self, name: str) -> tuple[Path, Path, str]:
        root = Path(tempfile.gettempdir()) / f"frameflow-t015-{name}-{uuid.uuid4().hex}"
        remote = root.parent / f"{root.name}-origin.git"
        run_command("git", "init", "--bare", str(remote))
        run_command("git", "init", str(root))
        run_command("git", "config", "user.name", "FRAMEFLOW Gate Test", cwd=root)
        run_command("git", "config", "user.email", "gate-test@example.invalid", cwd=root)
        (root / "skills" / "test-skill").mkdir(parents=True)
        (root / "README.txt").write_text("BASE\n", encoding="utf-8")
        (root / "skills" / "test-skill" / "skill.txt").write_text("stable\n", encoding="utf-8")
        run_command("git", "add", "--all", cwd=root)
        run_command("git", "commit", "-m", "fixture base", cwd=root)
        run_command("git", "branch", "-M", "main", cwd=root)
        base = run_command("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
        run_command("git", "remote", "add", "origin", str(remote), cwd=root)
        run_command("git", "push", "origin", "main", cwd=root)
        run_command("git", "branch", "dev/v5.3.2", cwd=root)
        run_command("git", "push", "origin", "dev/v5.3.2", cwd=root)
        run_command("git", "switch", "dev/v5.3.2", cwd=root)
        return root, remote, base

    def run_sync(self, root: Path, relative_path: str | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepositoryRoot",
            str(root),
            "-Remote",
            "origin",
            "-CommitMessage",
            "fixture safe sync",
        ]
        if relative_path is not None:
            args.extend(["-Path", relative_path])
        return run_command(*args, check=False)

    def git_text(self, root: Path, *args: str) -> str:
        return run_command("git", *args, cwd=root).stdout.strip()

    def test_g1_dev_push_isolation(self) -> None:
        root, remote, base = self.make_fixture("g1")
        (root / "skills" / "test-skill" / "skill.txt").write_text("dev change\n", encoding="utf-8")
        result = self.run_sync(root, "skills/test-skill/skill.txt")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SYNC PASS", result.stdout)
        local = self.git_text(root, "rev-parse", "HEAD")
        remote_dev = run_command("git", "--git-dir", str(remote), "rev-parse", "refs/heads/dev/v5.3.2").stdout.strip()
        remote_main = run_command("git", "--git-dir", str(remote), "rev-parse", "refs/heads/main").stdout.strip()
        self.assertEqual(remote_dev, local)
        self.assertEqual(remote_main, base)
        self.assertEqual(self.git_text(root, "branch", "--show-current"), "dev/v5.3.2")

    def test_g2_conflict_aborts_without_push_or_resolution(self) -> None:
        root, remote, _ = self.make_fixture("g2")
        (root / "conflict.txt").write_text("base\n", encoding="utf-8")
        run_command("git", "add", "conflict.txt", cwd=root)
        run_command("git", "commit", "-m", "add conflict file", cwd=root)
        run_command("git", "switch", "main", cwd=root)
        (root / "conflict.txt").write_text("main side\n", encoding="utf-8")
        run_command("git", "add", "conflict.txt", cwd=root)
        run_command("git", "commit", "-m", "main conflict side", cwd=root)
        run_command("git", "switch", "dev/v5.3.2", cwd=root)
        (root / "conflict.txt").write_text("dev side\n", encoding="utf-8")
        run_command("git", "add", "conflict.txt", cwd=root)
        run_command("git", "commit", "-m", "dev conflict side", cwd=root)
        before_remote = run_command("git", "--git-dir", str(remote), "rev-parse", "refs/heads/dev/v5.3.2").stdout.strip()
        conflict = run_command("git", "merge", "main", cwd=root, check=False)
        self.assertNotEqual(conflict.returncode, 0)
        result = self.run_sync(root, "conflict.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ABORT SAFE", result.stdout)
        conflict_status = self.git_text(root, "status", "--short")
        self.assertTrue("UU conflict.txt" in conflict_status or "AA conflict.txt" in conflict_status)
        after_remote = run_command("git", "--git-dir", str(remote), "rev-parse", "refs/heads/dev/v5.3.2").stdout.strip()
        self.assertEqual(after_remote, before_remote)

    def test_g3_branch_is_unchanged_before_and_after_sync(self) -> None:
        root, _, _ = self.make_fixture("g3")
        before = self.git_text(root, "branch", "--show-current")
        (root / "skills" / "test-skill" / "skill.txt").write_text("branch stays\n", encoding="utf-8")
        result = self.run_sync(root, "skills/test-skill/skill.txt")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, "dev/v5.3.2")
        self.assertEqual(self.git_text(root, "branch", "--show-current"), before)

    def test_g4_dirty_and_untracked_content_is_preserved(self) -> None:
        root, _, _ = self.make_fixture("g4")
        tracked = root / "tracked.txt"
        untracked = root / "untracked.txt"
        tracked.write_text("user tracked content\n", encoding="utf-8")
        untracked.write_text("user untracked content\n", encoding="utf-8")
        result = self.run_sync(root, "tracked.txt")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(tracked.read_text(encoding="utf-8"), "user tracked content\n")
        self.assertEqual(untracked.read_text(encoding="utf-8"), "user untracked content\n")
        self.assertIn("?? untracked.txt", self.git_text(root, "status", "--short"))

    def test_clean_tree_returns_no_changes_without_commit_or_push(self) -> None:
        root, remote, base = self.make_fixture("no-changes")
        result = self.run_sync(root, "skills/test-skill/skill.txt")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NO_CHANGES", result.stdout)
        self.assertEqual(self.git_text(root, "rev-parse", "HEAD"), base)
        remote_dev = run_command("git", "--git-dir", str(remote), "rev-parse", "refs/heads/dev/v5.3.2").stdout.strip()
        self.assertEqual(remote_dev, base)

    def test_g5_stable_skill_tag_restores_and_executes_contract(self) -> None:
        root, _, _ = self.make_fixture("g5")
        skill = root / "skills" / "test-skill" / "skill.py"
        stable_source = "def render(value):\n    return 'stable:' + value\n"
        skill.write_text(stable_source, encoding="utf-8")
        run_command("git", "add", "skill.py", cwd=skill.parent)
        run_command("git", "commit", "-m", "stable skill implementation", cwd=root)
        run_command("git", "tag", "-a", "stable-skill-snapshot", "-m", "stable skill snapshot", cwd=root)
        run_command("git", "switch", "main", cwd=root)
        run_command("git", "switch", "dev/v5.3.2", cwd=root)
        skill.write_text("def render(value):\n    raise RuntimeError('broken')\n", encoding="utf-8")
        restored = run_command("git", "show", "stable-skill-snapshot:skills/test-skill/skill.py", cwd=root).stdout
        skill.write_text(restored, encoding="utf-8")
        namespace: dict[str, object] = {}
        exec(compile(restored, str(skill), "exec"), namespace)
        self.assertEqual(namespace["render"]("legacy"), "stable:legacy")
        self.assertEqual(
            self.git_text(root, "rev-parse", "stable-skill-snapshot^{}"),
            self.git_text(root, "rev-parse", "HEAD"),
        )

    def test_g5_real_skill_snapshot_restores_and_executes_contract(self) -> None:
        self.assertEqual(
            run_command("git", "-C", str(SKILL_ROOT), "rev-parse", f"{SKILL_TAG}^{{}}").stdout.strip(),
            run_command("git", "-C", str(SKILL_ROOT), "rev-parse", "HEAD").stdout.strip(),
        )
        temp_root = Path(tempfile.gettempdir()) / f"frameflow-t015-real-skill-{uuid.uuid4().hex}"
        temp_root.mkdir()
        stable_script = temp_root / "character_asset_check.py"
        broken_script = temp_root / "character_asset_check.broken.py"
        input_file = temp_root / "character.json"
        stable_source = run_command(
            "git", "-C", str(SKILL_ROOT), "show", f"{SKILL_TAG}:{SKILL_CONTRACT}"
        ).stdout
        broken_script.write_text("raise RuntimeError('broken skill snapshot')\n", encoding="utf-8")
        stable_script.write_text(stable_source, encoding="utf-8")
        input_file.write_text(
            '{"characters":[{"id":"CHAR_STABLE","name":"Stable","priority":"B",'
            '"available_assets":["master_reference"],"face_identity_anchors":["face"],'
            '"hair_silhouette_anchors":["hair"],"costume_design_breakdown":["costume"],'
            '"body_and_motion_language":["motion"],"continuity_locks":["lock"]}]}',
            encoding="utf-8",
        )
        broken = run_command("python", str(broken_script), str(input_file), check=False)
        self.assertNotEqual(broken.returncode, 0)
        restored = run_command("python", str(stable_script), str(input_file), check=False)
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertIn("Readiness: ready", restored.stdout)


if __name__ == "__main__":
    unittest.main()
