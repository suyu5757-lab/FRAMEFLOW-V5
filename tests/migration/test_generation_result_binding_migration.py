from __future__ import annotations

import sqlite3
import os
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.online import downgrade_candidate, upgrade_candidate
from core.migration.validation import validate_candidate


_OLD_REVISION = "20260826_01"
_HEAD_REVISION = "20260830_01"


def _path(label: str) -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"])
    return root / f"t26-binding-{label}-{uuid4().hex}.db"


def _create_pre_binding_database(path: Path) -> None:
    """Create an isolated database at the exact pre-closure shape."""

    # Build through the real migration chain, then use the tested isolated
    # downgrade to obtain the exact pre-closure schema without hand-editing
    # SQLite's circular foreign-key DDL.
    upgrade_candidate(path)
    downgrade_candidate(path, _OLD_REVISION)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        assert all(
            row[1] != "generation_id"
            for row in connection.execute('PRAGMA table_info("artifacts")')
        )
        connection.execute(
            'UPDATE "alembic_version" SET "version_num"=?',
            (_OLD_REVISION,),
        )
        connection.commit()
    finally:
        connection.close()


def _seed_generation(connection: sqlite3.Connection) -> None:
    connection.execute(
        'INSERT INTO "projects"(id,title,aspect_ratio,fps,target_duration) VALUES(?,?,?,?,?)',
        ("P1", "Binding Test", "16:9", 24, 5),
    )
    connection.execute(
        'INSERT INTO "sequences"(id,project_id,order_index) VALUES(?,?,?)',
        ("SEQ1", "P1", 1),
    )
    connection.execute(
        'INSERT INTO "shots"(id,project_id,sequence_id,shot_spec_json) VALUES(?,?,?,?)',
        ("SH1", "P1", "SEQ1", "{}"),
    )
    connection.execute(
        'INSERT INTO "artifacts"(id,project_id,shot_id,type,role,path,version) '
        'VALUES(?,?,?,?,?,?,?)',
        ("PKG1", "P1", "SH1", "json", "package_manifest", "package.json", "v1"),
    )
    connection.execute(
        'INSERT INTO "generations"(id,shot_id,package_manifest_artifact_id,provider) '
        'VALUES(?,?,?,?)',
        ("GEN1", "SH1", "PKG1", "manual"),
    )


def _artifact_ids(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            'SELECT id FROM "artifacts" ORDER BY id'
        ).fetchall()
    ]


def test_fresh_upgrade_has_nullable_fk_and_index() -> None:
    path = _path("fresh")
    upgrade_candidate(path)
    result = validate_candidate(path)
    assert result["errors"] == []

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            'SELECT version_num FROM "alembic_version"'
        ).fetchone() == (_HEAD_REVISION,)
        column = next(
            row for row in connection.execute('PRAGMA table_info("artifacts")')
            if row[1] == "generation_id"
        )
        assert column[3] == 0
        foreign_keys = connection.execute('PRAGMA foreign_key_list("artifacts")').fetchall()
        assert any(row[2:5] == ("generations", "generation_id", "id") for row in foreign_keys)
        indexes = connection.execute('PRAGMA index_list("artifacts")').fetchall()
        assert any(row[1] == "ix_artifacts_generation_id" for row in indexes)
        assert len(connection.execute(
            'SELECT name FROM sqlite_master WHERE type="table"'
        ).fetchall()) == 12
    finally:
        connection.close()


def test_existing_pre_migration_data_upgrades_without_heuristic_backfill() -> None:
    path = _path("existing")
    _create_pre_binding_database(path)
    connection = sqlite3.connect(path)
    try:
        _seed_generation(connection)
        before_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in (
                "projects", "sequences", "shots", "assets", "artifacts", "generations",
                "tasks", "events", "resource_locks", "provider_submissions", "reviews",
            )
        }
        connection.commit()
    finally:
        connection.close()

    upgrade_candidate(path)
    connection = sqlite3.connect(path)
    try:
        after_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in before_counts
        }
        assert after_counts == before_counts
        assert connection.execute(
            'SELECT generation_id FROM "artifacts" WHERE id="PKG1"'
        ).fetchone() == (None,)
    finally:
        connection.close()
    assert validate_candidate(path)["errors"] == []


def test_package_input_and_multiple_generation_outputs_are_distinct() -> None:
    path = _path("semantics")
    upgrade_candidate(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        _seed_generation(connection)
        connection.executemany(
            'INSERT INTO "artifacts"(id,project_id,shot_id,type,role,path,version,generation_id) '
            'VALUES(?,?,?,?,?,?,?,?)',
            [
                ("RESULT1", "P1", "SH1", "video", "provider_result", "result-1.mp4", "v1", "GEN1"),
                ("RESULT2", "P1", "SH1", "video", "provider_result", "result-2.mp4", "v1", "GEN1"),
            ],
        )
        connection.commit()
        assert connection.execute(
            'SELECT generation_id FROM "artifacts" WHERE id="PKG1"'
        ).fetchone() == (None,)
        assert connection.execute(
            'SELECT COUNT(*) FROM "artifacts" WHERE generation_id="GEN1"'
        ).fetchone() == (2,)
        assert connection.execute(
            'SELECT role FROM "artifacts" WHERE generation_id="GEN1" ORDER BY id'
        ).fetchall() == [("provider_result",), ("provider_result",)]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                'INSERT INTO "artifacts"(id,project_id,type,role,path,version,generation_id) '
                'VALUES(?,?,?,?,?,?,?)',
                ("BAD", "P1", "video", "provider_result", "bad.mp4", "v1", "GEN404"),
            )
    finally:
        connection.close()


def test_downgrade_on_isolated_copy_and_reupgrade_restore_relation() -> None:
    path = _path("cycle")
    upgrade_candidate(path)
    connection = sqlite3.connect(path)
    try:
        _seed_generation(connection)
        connection.execute(
            'INSERT INTO "artifacts"(id,project_id,shot_id,type,role,path,version,generation_id) '
            'VALUES(?,?,?,?,?,?,?,?)',
            ("RESULT1", "P1", "SH1", "video", "provider_result", "result.mp4", "v1", "GEN1"),
        )
        connection.commit()
    finally:
        connection.close()

    downgrade_candidate(path, _OLD_REVISION)
    connection = sqlite3.connect(path)
    try:
        assert all(
            row[1] != "generation_id"
            for row in connection.execute('PRAGMA table_info("artifacts")')
        )
        assert all(
            row[1] != "ix_artifacts_generation_id"
            for row in connection.execute('PRAGMA index_list("artifacts")')
        )
        assert _artifact_ids(connection) == ["PKG1", "RESULT1"]
    finally:
        connection.close()

    upgrade_candidate(path)
    assert validate_candidate(path)["errors"] == []
