"""Add the nullable Generation-to-result Artifact provenance relation."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, ForeignKey, String, inspect


revision = "20260830_01"
down_revision = "20260826_01"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_artifacts_generation_id"


def _artifact_columns(bind: object) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(bind).get_columns("artifacts")  # type: ignore[arg-type]
    }


def _has_generation_fk(bind: object) -> bool:
    for foreign_key in inspect(bind).get_foreign_keys("artifacts"):  # type: ignore[arg-type]
        if (
            foreign_key.get("constrained_columns") == ["generation_id"]
            and foreign_key.get("referred_table") == "generations"
            and foreign_key.get("referred_columns") == ["id"]
        ):
            return True
    return False


def _has_generation_index(bind: object) -> bool:
    return any(
        str(index.get("name")) == _INDEX_NAME
        for index in inspect(bind).get_indexes("artifacts")  # type: ignore[arg-type]
    )


def upgrade() -> None:
    """Add ``artifacts.generation_id`` without heuristic data backfill."""

    bind = op.get_bind()
    columns = _artifact_columns(bind)
    if "generation_id" not in columns:
        if bind.dialect.name == "sqlite":  # type: ignore[attr-defined]
            # SQLite can add this nullable FK directly. This preserves the
            # existing generations.package_manifest_artifact_id reverse FK
            # without rebuilding or temporarily disabling foreign_keys.
            op.execute(
                'ALTER TABLE "artifacts" ADD COLUMN "generation_id" '
                'VARCHAR(120) REFERENCES "generations" ("id") ON DELETE RESTRICT'
            )
        else:  # pragma: no cover - Runtime MVP is SQLite-only
            op.add_column(
                "artifacts",
                Column(
                    "generation_id",
                    String(120),
                    ForeignKey("generations.id", ondelete="RESTRICT"),
                    nullable=True,
                ),
            )
    elif not _has_generation_fk(bind):
        raise RuntimeError(
            "artifacts.generation_id exists without the canonical FK to generations.id"
        )

    if not _has_generation_index(bind):
        op.create_index(_INDEX_NAME, "artifacts", ["generation_id"], unique=False)


def downgrade() -> None:
    """Remove only the closure relation on an isolated database."""

    bind = op.get_bind()
    if "generation_id" not in _artifact_columns(bind):
        return
    if bind.dialect.name == "sqlite":  # type: ignore[attr-defined]
        # SQLite cannot rebuild this table while the reverse
        # generations.package_manifest_artifact_id FK is enforced. Validate
        # the database first, then use the SQLite schema-rebuild escape hatch
        # only for this isolated downgrade operation and restore FK enforcement
        # before returning. Normal Runtime lifecycle tests always run FK=ON.
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
            raise RuntimeError("SQLite downgrade requires foreign_keys=ON before rebuild")
        if bind.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
            raise RuntimeError("SQLite downgrade refuses a database with FK violations")
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            if _has_generation_index(bind):
                op.drop_index(_INDEX_NAME, table_name="artifacts")
            with op.batch_alter_table("artifacts", recreate="always") as batch_op:
                batch_op.drop_column("generation_id")
        finally:
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")
    else:  # pragma: no cover - Runtime MVP is SQLite-only
        if _has_generation_index(bind):
            op.drop_index(_INDEX_NAME, table_name="artifacts")
        op.drop_column("artifacts", "generation_id")
