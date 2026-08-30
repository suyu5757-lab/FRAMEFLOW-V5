"""FRAMEFLOW V5.3.2 Runtime MVP declarative schema.

This module is a declaration only. It does not open or migrate the production
database. The Alembic revision under ``core/migration`` is offline-first and
is the only migration surface for this T02 task.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)


metadata = MetaData()

RUNTIME_PRAGMA_STATEMENTS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
)

RUNTIME_TABLE_NAMES = (
    "projects",
    "sequences",
    "shots",
    "assets",
    "artifacts",
    "tasks",
    "events",
    "resource_locks",
    "generations",
    "provider_submissions",
    "reviews",
)

PROVIDER_CAPABILITY_V22_FIELDS = (
    "provider",
    "supports_first_frame",
    "supports_last_frame",
    "max_duration",
    "max_images",
    "manual_only",
    "estimated_cost_per_submit",
    "last_verified_at",
)
PROVIDER_CAPABILITY_V22_DEFAULTS = {
    "estimated_cost_per_submit": None,
    "last_verified_at": None,
}

_SHOT_STATUS = (
    "DRAFT",
    "SPEC_READY",
    "ASSET_READY",
    "PACKAGE_READY",
    "SUBMITTED",
    "GENERATING",
    "RESULT_READY",
    "QA_APPROVED",
    "RETRY_REQUIRED",
    "DELIVERED",
)
TASK_STATUS_VALUES = (
    "CREATED",
    "QUEUED",
    "WAITING_FOR_RESOURCE",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "INTERRUPTED",
    "CANCELLED",
)
_TASK_STATUS = TASK_STATUS_VALUES


projects = Table(
    "projects",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("title", String(255), nullable=False),
    Column("aspect_ratio", String(32), nullable=False),
    Column("fps", Float, nullable=False),
    Column("target_duration", Float, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'DRAFT'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

sequences = Table(
    "sequences",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("project_id", String(120), ForeignKey("projects.id"), nullable=False),
    Column("order_index", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("project_id", "order_index", name="uq_sequences_project_order"),
)

shots = Table(
    "shots",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("project_id", String(120), ForeignKey("projects.id"), nullable=False),
    Column("sequence_id", String(120), ForeignKey("sequences.id"), nullable=False),
    Column("shot_spec_json", Text, nullable=False),
    Column("metadata_json", Text, nullable=False, server_default=text("'{}'")),
    Column("continuity_in", Text),
    Column("continuity_out", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("length(shot_spec_json) > 0", name="ck_shots_spec_present"),
)

assets = Table(
    "assets",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("project_id", String(120), ForeignKey("projects.id"), nullable=False),
    Column("type", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'DRAFT'")),
    Column("version", String(64), nullable=False),
    # Kept as an ID instead of an FK to avoid a circular create-order dependency
    # with artifacts.asset_id while preserving the required provenance link.
    Column("master_artifact_id", String(120)),
    Column("locked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("project_id", String(120), ForeignKey("projects.id"), nullable=False),
    Column("shot_id", String(120), ForeignKey("shots.id")),
    Column("asset_id", String(120), ForeignKey("assets.id")),
    Column("type", String(64), nullable=False),
    Column("role", String(64), nullable=False),
    Column("path", Text, nullable=False),
    Column("sha256", String(128)),
    Column("version", String(64), nullable=False),
    Column("source_task_id", String(120)),
    Column("source_artifacts_json", Text, nullable=False, server_default=text("'[]'")),
    # Nullable output-side provenance: input/reference artifacts remain NULL;
    # generated/imported result artifacts point to their owning Generation.
    Column(
        "generation_id",
        String(120),
        ForeignKey("generations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    ),
    Column("status", String(32), nullable=False, server_default=text("'DRAFT'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("type", String(64), nullable=False),
    Column("project_id", String(120), ForeignKey("projects.id"), nullable=False),
    Column("shot_id", String(120), ForeignKey("shots.id")),
    Column("status", String(32), nullable=False, server_default=text("'CREATED'")),
    Column("priority", Integer, nullable=False, server_default=text("0")),
    Column("idempotency_key", String(512)),
    Column("attempt", Integer, nullable=False, server_default=text("0")),
    Column("max_attempts", Integer, nullable=False, server_default=text("3")),
    Column("timeout", Integer),
    Column("worker", String(120)),
    Column("payload_json", Text, nullable=False, server_default=text("'{}'")),
    Column("result_json", Text),
    Column("error_json", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("started_at", DateTime(timezone=True)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('CREATED','QUEUED','WAITING_FOR_RESOURCE','RUNNING','SUCCEEDED','FAILED','INTERRUPTED','CANCELLED')",
        name="ck_tasks_status",
    ),
)

events = Table(
    "events",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("trace_id", String(120), nullable=False),
    Column("entity_type", String(64), nullable=False),
    Column("entity_id", String(120), nullable=False),
    Column("event_type", String(120), nullable=False),
    Column("payload", Text, nullable=False, server_default=text("'{}'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

resource_locks = Table(
    "resource_locks",
    metadata,
    Column("resource_id", String(64), primary_key=True),
    Column("owner_task_id", String(120), ForeignKey("tasks.id"), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False),
    Column("lease_timeout", Integer, nullable=False, server_default=text("300")),
    Column("status", String(32), nullable=False, server_default=text("'HELD'")),
)

generations = Table(
    "generations",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("shot_id", String(120), ForeignKey("shots.id"), nullable=False),
    Column("package_manifest_artifact_id", String(120), ForeignKey("artifacts.id"), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'CREATED'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

provider_submissions = Table(
    "provider_submissions",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("generation_id", String(120), ForeignKey("generations.id"), nullable=False),
    Column("provider", String(64), nullable=False),
    # The value is composed with PRJ + SH + package_version + shot_spec_version
    # + provider + provider_config_hash; keep the full key auditable here.
    Column(
        "idempotency_key",
        String(1024),
        nullable=False,
        comment="PRJ + SH + package_version + shot_spec_version + provider + provider_config_hash",
    ),
    Column("request_hash", String(128), nullable=False),
    Column("external_task_id", String(255)),
    Column("attempt", Integer, nullable=False, server_default=text("0")),
    Column("status", String(32), nullable=False, server_default=text("'CREATED'")),
    Column("submitted_at", DateTime(timezone=True)),
    UniqueConstraint("idempotency_key", name="uq_provider_submissions_idempotency"),
)

reviews = Table(
    "reviews",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("shot_id", String(120), ForeignKey("shots.id"), nullable=False),
    Column("generation_id", String(120), ForeignKey("generations.id")),
    Column("qa_json", Text, nullable=False, server_default=text("'{}'")),
    Column("decision", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


def runtime_table_names() -> tuple[str, ...]:
    """Return the stable, ordered Runtime MVP table list."""

    return RUNTIME_TABLE_NAMES
