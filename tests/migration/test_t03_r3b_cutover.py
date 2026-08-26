from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.migration.cutover import (
    CANONICAL_DATABASE_PATH,
    CutoverBlocked,
    DEFAULT_CUTOVER_STAGING_ROOT,
    cutover_path_info,
    default_cutover_staging_root,
    fresh_candidate_from_production,
    perform_production_cutover,
)


class T03R3BSameVolumeTests(TestCase):
    def test_default_production_staging_is_on_the_canonical_volume(self) -> None:
        staging = default_cutover_staging_root()
        info = cutover_path_info(
            staging / "run-001" / "candidate_v5.db",
            CANONICAL_DATABASE_PATH,
            staging / "run-001" / "legacy_frameflow_v3.db",
        )
        self.assertEqual(DEFAULT_CUTOVER_STAGING_ROOT, staging)
        self.assertEqual("D:", info["candidate_volume"])
        self.assertEqual("D:", info["production_volume"])
        self.assertEqual("D:", info["archive_volume"])
        self.assertTrue(info["same_volume"])

    def test_cross_volume_staging_aborts_before_any_replace(self) -> None:
        candidate = Path(r"C:\frameflow-t03r3b\candidate_v5.db")
        archive = Path(r"D:\frameflow-t03r3b\legacy_frameflow_v3.db")
        with patch("core.migration.cutover.shutil.move") as move, patch(
            "core.migration.cutover.os.replace"
        ) as replace:
            with self.assertRaisesRegex(CutoverBlocked, "same-volume guard"):
                perform_production_cutover(
                    candidate,
                    legacy_archive=archive,
                    production_cutover=True,
                    no_active_writer=lambda: True,
                )
        move.assert_not_called()
        replace.assert_not_called()

    def test_candidate_factory_rejects_cross_volume_default_staging(self) -> None:
        with self.assertRaisesRegex(CutoverBlocked, "same-volume staging"):
            fresh_candidate_from_production(
                source=CANONICAL_DATABASE_PATH,
                staging_root=Path(r"C:\frameflow-t03r3b"),
                run_id="cross-volume-test",
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
