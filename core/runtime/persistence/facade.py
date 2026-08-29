"""Typed application persistence facade backed by the V5 StateStore.

The facade deliberately covers only the non-queue application reads and basic
project metadata write needed by the existing Workbench shell. Task claiming,
retry, cancellation semantics, heartbeats, workers, providers, and other
future orchestration behavior remain outside T03-R2.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import delete

from core.migration.legacy_compat import LegacyReadOnlyCompatibility, LegacyReadOnlyError
from core.schemas.runtime_mvp import metadata
from core.runtime.readiness import CAPABILITIES, evaluate_capabilities, readiness_summary
from core.runtime.state_store import StateStore

class RuntimePersistenceError(RuntimeError):
    """Raised for unsupported V5 application operations."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _timestamp(value: Any) -> str:
    if value is None:
        return _now()
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


class RuntimePersistence:
    """Application contract over one V5 StateStore and optional legacy reader."""

    mode = "v5"

    def __init__(self, store: StateStore, *, legacy_path: Path | None = None) -> None:
        self.store = store
        self.legacy_path = legacy_path.resolve(strict=False) if legacy_path else None
        self._legacy = (
            LegacyReadOnlyCompatibility(self.legacy_path) if self.legacy_path else None
        )

    @property
    def path(self) -> Path:
        return self.store.path

    def close(self) -> None:
        self.dispose()

    def dispose(self) -> None:
        """Release the StateStore and its SQLAlchemy pool explicitly."""

        self.store.dispose()

    def __enter__(self) -> "RuntimePersistence":
        return self

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.dispose()

    @staticmethod
    def encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def decode(value: str | None, default: Any = None) -> Any:
        return _json(value, default)

    def connect(self) -> None:
        raise RuntimePersistenceError(
            "V5 application code must use RuntimePersistence methods; raw SQL connections are not exposed"
        )

    def runtime_sqlite_contract(self) -> dict[str, Any]:
        """Return SQLite settings from this running facade's StateStore pool."""

        pragmas = self.store.pragmas()
        return {
            "database": str(self.path),
            "journal_mode": str(pragmas["journal_mode"]).lower(),
            "foreign_keys": int(pragmas["foreign_keys"]),
            "busy_timeout": int(pragmas["busy_timeout"]),
        }

    def _revision(self, project_id: str) -> int:
        updates = [
            event
            for event in self.store.list("events")
            if event.get("entity_type") == "project"
            and event.get("entity_id") == project_id
            and event.get("event_type") == "project.updated"
        ]
        return 1 + len(updates)

    def _project_row(self, project_id: str) -> dict[str, Any] | None:
        row = self.store.get_project(project_id)
        return row

    @staticmethod
    def _shot_payload(row: Mapping[str, Any]) -> dict[str, Any]:
        spec = _json(row.get("shot_spec_json"), {})
        if not isinstance(spec, dict):
            spec = {}
        shot_id = _text(row.get("id"))
        camera = spec.get("camera") if isinstance(spec.get("camera"), dict) else {}
        payload = dict(spec)
        payload.update(
            {
                "id": shot_id,
                "shot_id": shot_id,
                "sequence_id": row.get("sequence_id"),
                "duration": spec.get("duration_sec", 1),
                "purpose": spec.get("story_purpose", ""),
                "action": spec.get("subject_action", ""),
                "size": camera.get("size") or "",
                "camera": camera,
                "status": str(spec.get("status") or "DRAFT").lower(),
            }
        )
        requirements: list[dict[str, Any]] = []
        for asset_id in [*(spec.get("characters") or []), *(spec.get("props") or [])]:
            requirements.append(
                {
                    "assetId": str(asset_id),
                    "assetClass": "character" if asset_id in (spec.get("characters") or []) else "prop",
                    "role": "shot reference",
                    "required": True,
                    "requiredReadiness": "registered",
                }
            )
        payload["assetRequirements"] = requirements
        return payload

    @staticmethod
    def _artifact_payload(row: Mapping[str, Any]) -> dict[str, Any]:
        path = row.get("path")
        return {
            "id": row.get("id"),
            "artifact_id": row.get("id"),
            "project_id": row.get("project_id"),
            "asset_id": row.get("asset_id"),
            "type": row.get("type"),
            "artifact_type": row.get("type"),
            "role": row.get("role"),
            "path": path,
            "local_path": path,
            "sha256": row.get("sha256"),
            "version": row.get("version"),
            "status": row.get("status"),
            "qa_decision": "Pending",
            "metadata": _json(row.get("source_artifacts_json"), {}),
            "created_at": _timestamp(row.get("created_at")),
        }

    def _project_document(self, row: Mapping[str, Any]) -> dict[str, Any]:
        project_id = _text(row.get("id"))
        event_metadata: dict[str, Any] = {}
        project_events = [
            event
            for event in self.store.list("events")
            if event.get("entity_type") == "project" and event.get("entity_id") == project_id
        ]
        for event in sorted(project_events, key=lambda item: _timestamp(item.get("created_at"))):
            payload = _json(event.get("payload"), {})
            if isinstance(payload, dict):
                event_metadata.update(payload)
        shots = [
            self._shot_payload(item)
            for item in self.store.list_shots()
            if _text(item.get("project_id")) == project_id
        ]
        artifacts = [
            self._artifact_payload(item)
            for item in self.store.list_artifacts()
            if _text(item.get("project_id")) == project_id
        ]
        artifacts_by_asset: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            if artifact.get("asset_id"):
                artifacts_by_asset.setdefault(str(artifact["asset_id"]), []).append(artifact)
        assets: list[dict[str, Any]] = []
        for item in self.store.list_assets():
            if _text(item.get("project_id")) != project_id:
                continue
            asset_id = _text(item.get("id"))
            status = _text(item.get("status"), "DRAFT")
            linked = artifacts_by_asset.get(asset_id, [])
            assets.append(
                {
                    "id": asset_id,
                    "name": asset_id,
                    "assetClass": _text(item.get("type"), "unknown"),
                    "assetRole": _text(item.get("type"), "asset"),
                    "grade": "B",
                    "required": False,
                    "status": status.lower(),
                    "assetMetadata": {"v5_status": status},
                    "artifactId": item.get("master_artifact_id"),
                    "artifacts": linked,
                }
            )
        lifecycle = "archived" if _text(row.get("status")).upper() == "ARCHIVED" else "active"
        production = "completed" if _text(row.get("status")).upper() in {"QA_APPROVED", "DELIVERED"} else "in_progress"
        document = {
            "id": project_id,
            "name": _text(row.get("title"), project_id),
            "brief": _text(event_metadata.get("brief")),
            "ratio": _text(row.get("aspect_ratio"), "16:9"),
            "fps": float(row.get("fps") or 24),
            "duration": float(row.get("target_duration") or 0),
            "generator": _text(event_metadata.get("generator"), "v5-runtime"),
            "stage": 0,
            "sortOrder": 0,
            "productionStatus": production,
            "lifecycleStatus": lifecycle,
            "createdAt": _timestamp(row.get("created_at")),
            "updatedAt": _timestamp(row.get("updated_at")),
            "script": "",
            "scenes": [],
            "shots": shots,
            "assets": assets,
            "audio": {},
            "generations": [],
            "seedancePackages": [],
            "providerOverrides": {},
            "undoStack": [],
            "scriptVersions": [],
            "storyboardVersions": [],
            "storyWorkflowRuns": [],
        }
        if event_metadata.get("name") is not None:
            document["name"] = str(event_metadata["name"])
        if event_metadata.get("productionStatus") is not None:
            document["productionStatus"] = str(event_metadata["productionStatus"])
        if event_metadata.get("sortOrder") is not None:
            document["sortOrder"] = event_metadata["sortOrder"]
        return document

    def project_envelope(self, project_id: str) -> dict[str, Any]:
        row = self._project_row(project_id)
        if row is None:
            raise KeyError(project_id)
        document = self._project_document(row)
        return {
            "document": document,
            "revision": self._revision(project_id),
            "updated_at": _timestamp(row.get("updated_at")),
            "lifecycle_status": document.get("lifecycleStatus"),
        }

    def list_projects_envelope(self, *, include_archived: bool = False) -> dict[str, Any]:
        projects = []
        for row in self.store.list_projects():
            document = self._project_document(row)
            if not include_archived and document["lifecycleStatus"] != "active":
                continue
            projects.append(
                {
                    "document": document,
                    "revision": self._revision(_text(row.get("id"))),
                    "updated_at": _timestamp(row.get("updated_at")),
                    "lifecycle_status": document["lifecycleStatus"],
                }
            )
        projects.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"projects": projects}

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        ratio: str,
        duration: float,
        generator: str,
        brief: str,
    ) -> dict[str, Any]:
        created = datetime.now(UTC)
        row = self.store.create_project(
            project_id,
            name,
            ratio,
            24,
            duration,
            status="DRAFT",
            event={
                "entity_type": "project",
                "entity_id": project_id,
                "event_type": "project.created",
                "payload": {"generator": generator, "brief": brief},
                "created_at": created,
            },
        )
        self.store.create_sequence(f"{project_id}:SQ001", project_id, 1)
        envelope = self.project_envelope(project_id)
        envelope["document"].update({"generator": generator, "brief": brief})
        return {"ok": True, **envelope}

    def update_project_metadata(
        self, project_id: str, *, expected_revision: int, changes: Mapping[str, Any]
    ) -> dict[str, Any]:
        current = self._project_row(project_id)
        if current is None:
            raise KeyError(project_id)
        actual = self._revision(project_id)
        if actual != expected_revision:
            raise ValueError(f"project revision conflict: expected={expected_revision} actual={actual}")
        project_changes: dict[str, Any] = {}
        if changes.get("name") is not None:
            project_changes["title"] = str(changes["name"])
        if changes.get("ratio") is not None:
            project_changes["aspect_ratio"] = str(changes["ratio"])
        if changes.get("duration") is not None:
            project_changes["target_duration"] = float(changes["duration"])
        lifecycle = changes.get("lifecycleStatus")
        if lifecycle is not None:
            project_changes["status"] = "ARCHIVED" if lifecycle == "archived" else "DRAFT"
        event = {
            "entity_type": "project",
            "entity_id": project_id,
            "event_type": "project.updated",
            "payload": dict(changes),
            "created_at": datetime.now(UTC),
        }
        self.store.update_project(project_id, project_changes, event=event)
        envelope = self.project_envelope(project_id)
        envelope["document"]["productionStatus"] = changes.get(
            "productionStatus", envelope["document"].get("productionStatus")
        )
        envelope["document"]["sortOrder"] = changes.get("sortOrder", envelope["document"].get("sortOrder", 0))
        return {"ok": True, **envelope}

    def delete_smoke_fixture(self, project_id: str) -> None:
        """Remove only an explicitly named T03-R3 validation project.

        Production cleanup remains inside the same V5 transaction boundary as
        normal application persistence.  The prefix guard prevents this
        helper from becoming a general project deletion API.
        """

        if not project_id.startswith(("T03R3_SMOKE_", "T03R3B_SMOKE_", "T03R3C_SMOKE_")):
            raise RuntimePersistenceError("only T03R3*SMOKE_ fixtures may be cleaned up")
        with self.store.transaction() as connection:
            events = metadata.tables["events"]
            sequences = metadata.tables["sequences"]
            projects = metadata.tables["projects"]
            connection.execute(delete(events).where(events.c.entity_id.in_((project_id, f"{project_id}:SQ001"))))
            connection.execute(delete(sequences).where(sequences.c.project_id == project_id))
            connection.execute(delete(projects).where(projects.c.id == project_id))

    def health_payload(self) -> dict[str, Any]:
        inputs = (
            self._legacy.provider_readiness_inputs(CAPABILITIES)
            if self._legacy is not None
            else {
                "profiles": {},
                "bindings": {},
                "source": {
                    "kind": "legacy_readonly_archive",
                    "path": None,
                    "available": False,
                    "reason": "legacy archive is not configured",
                },
            }
        )
        capabilities = evaluate_capabilities(inputs["bindings"], inputs["profiles"])
        readiness = readiness_summary(capabilities)
        return {
            "status": readiness["status"],
            "ok": readiness["ok"],
            "ready": readiness["ready"],
            "degraded": readiness["degraded"],
            "version": "5.3.2",
            "schema_version": 22,
            "openai_configured": bool(
                capabilities.get("image", {}).get("provider_profile_id")
                or capabilities.get("orchestrator", {}).get("provider_profile_id")
            ),
            "audio": any(
                bool(capabilities.get(key, {}).get("ready"))
                for key in ("tts", "music", "sfx")
            ),
            "images": bool(
                capabilities.get("image", {}).get("ready")
                or capabilities.get("image_edit", {}).get("ready")
            ),
            "seedance": bool(capabilities.get("video", {}).get("ready")),
            "runtime_mode": "v5",
            "capabilities": capabilities,
            "readiness": readiness,
            "readiness_source": inputs["source"],
        }

    def settings_payload(self) -> dict[str, Any]:
        return {
            "settings_version": "5.3.2",
            "system": {
                "runtime": "v5",
                "version": "5.3.2",
                "schema_version": 22,
                "database": {"path": str(self.path), "status": "ready"},
                "keyring": {"available": False, "backend": None},
                "media": {"ffmpeg": None, "ffprobe": None},
                "openai": {"profile_id": None, "credential_configured": False},
                "disk_free_bytes": 0,
                "provider_count": 0,
            },
            "providers": [],
            "presets": [],
            "bindings": [],
            "capabilities": list(CAPABILITIES),
            "orchestrator_models": {"default": "", "models": []},
            "routing_policy": "Provider 与执行语义属于后续 Task。",
        }

    def _project_summary(self, row: Mapping[str, Any]) -> dict[str, Any]:
        document = self._project_document(row)
        shots = document.get("shots") or []
        ready = sum(1 for shot in shots if str(shot.get("status")) in {"ready", "spec_ready", "package_ready"})
        total = len(shots)
        status = "completed" if total and ready == total else "in_progress" if total else "not_started"
        return {
            "project_id": document["id"],
            "name": document["name"],
            "ratio": document["ratio"],
            "duration": document["duration"],
            "generator": document["generator"],
            "status": status,
            "progress": {"completed": ready, "total": total, "percent": round(ready / total * 100) if total else 0},
            "current_stage_id": "shots" if total else "project",
            "current_stage_label": "镜头" if total else "项目",
            "blocker_count": total - ready,
            "review_count": 0,
            "next_task": None,
            "updated_at": _timestamp(row.get("updated_at")),
        }

    def dashboard_payload(self, project_id: str | None = None) -> dict[str, Any]:
        rows = self.store.list_projects()
        summaries = [self._project_summary(row) for row in rows]
        selected_row = next((row for row in rows if _text(row.get("id")) == project_id), None) if project_id else None
        selected = None
        if selected_row is not None:
            summary = self._project_summary(selected_row)
            selected = {
                "project": summary,
                "stages": [],
                "primary_next_task": None,
                "task_queue": [],
                "metrics": {"content": {}, "assets": {}, "execution": {}, "delivery": {}},
                "recent_activity": [],
                "source_revisions": {"project": self._revision(_text(selected_row.get("id"))), "graph": 0, "timeline": 0},
            }
        return {"generated_at": _now(), "projects": summaries, "selected_project": selected}

    def graph_envelope(self, project_id: str) -> dict[str, Any]:
        row = self._project_row(project_id)
        if row is None:
            raise KeyError(project_id)
        return {
            "project_id": project_id,
            "revision": 0,
            "graph": {"version": 1, "template_id": None, "nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {"runtime_mode": "v5"}},
            "updated_at": _timestamp(row.get("updated_at")),
        }

    def timeline_envelope(self, project_id: str) -> dict[str, Any]:
        row = self._project_row(project_id)
        if row is None:
            raise KeyError(project_id)
        return {
            "project_id": project_id,
            "revision": 0,
            "document": {"version": 1, "fps": float(row.get("fps") or 24), "width": 1920, "height": 1080, "duration": float(row.get("target_duration") or 0), "tracks": [], "metadata": {"runtime_mode": "v5"}},
            "updated_at": _timestamp(row.get("updated_at")),
        }

    def timeline_preflight(self, project_id: str) -> dict[str, Any]:
        document = self.project_envelope(project_id)["document"]
        shots = document.get("shots") or []
        rows = [
            {"shot_id": shot["id"], "scene_id": str(shot.get("scene") or "S_UNKNOWN"), "order": index, "duration": shot.get("duration", 1), "status": shot.get("status", "draft"), "clip_ids": [], "artifact_ids": [], "purpose": shot.get("purpose", ""), "camera": str(shot.get("camera") or ""), "action": shot.get("action", ""), "blockers": [{"code": "no_clip", "message": "V5 timeline clip persistence is not part of T03-R2.", "source": "runtime"}]}
            for index, shot in enumerate(shots, start=1)
        ]
        return {"project_id": project_id, "timeline_revision": 0, "summary": {"shot_total": len(rows), "shot_placed": 0, "shot_ready": 0, "blocked_shots": len(rows), "audio_ready": 0, "caption_count": 0, "delivery_ready": False, "error_count": len(rows), "warning_count": 0}, "shots": rows, "tracks": [], "warnings": [], "deliverables": {"master_burn_in": "", "clean": "", "srt": ""}, "asset_summary": {}}

    def _asset_payload(self, row: Mapping[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        status = _text(row.get("status"), "DRAFT").upper()
        ready = status in {"LOCKED", "APPROVED", "QA_APPROVED"} and bool(artifacts or row.get("master_artifact_id"))
        asset_class = _text(row.get("type"), "unknown")
        asset = {
            "id": row.get("id"),
            "name": row.get("id"),
            "assetClass": asset_class,
            "assetRole": asset_class,
            "assetMetadata": {"v5_status": status},
            "status": status.lower(),
            "grade": "B",
            "required": False,
            "artifacts": artifacts,
            "artifact_count": len(artifacts),
            "readiness": {"status": "ready" if ready else "missing", "kind": "production", "required": False, "grade": "B", "ready": ready, "registered_ready": bool(artifacts), "production_ready": ready, "next_action": None if ready else "等待 artifact", "missing": [] if ready else ["artifact"]},
            "registered_ready": bool(artifacts),
            "production_ready": ready,
            "next_action": None if ready else "等待 artifact",
            "references": [],
            "dependencies": [],
            "comparisons": [],
            "versions": [],
            "promptVersions": [],
            "workflow": {"status": "ready" if ready else "not_started", "next_action": None if ready else "等待 artifact"},
        }
        return asset

    def asset_library(self, project_id: str) -> dict[str, Any]:
        if self._project_row(project_id) is None:
            raise KeyError(project_id)
        artifacts = [
            self._artifact_payload(row)
            for row in self.store.list_artifacts()
            if _text(row.get("project_id")) == project_id
        ]
        assets = []
        for row in self.store.list_assets():
            if _text(row.get("project_id")) != project_id:
                continue
            links = [artifact for artifact in artifacts if artifact.get("asset_id") == row.get("id")]
            assets.append(self._asset_payload(row, links))
        ready = sum(1 for asset in assets if asset["readiness"]["ready"])
        by_class: dict[str, int] = {}
        for asset in assets:
            by_class[asset["assetClass"]] = by_class.get(asset["assetClass"], 0) + 1
        return {"project_id": project_id, "assets": assets, "summary": {"total": len(assets), "ready": ready, "blocked": 0, "missing_required_a": 0, "registered_ready": sum(1 for asset in assets if asset["registered_ready"]), "production_ready": sum(1 for asset in assets if asset["production_ready"]), "artifact_count": len(artifacts), "by_class": by_class, "by_status": {}}, "storage_integrity": {"ok": None, "status": "not_checked", "message": "T03-R2 does not run a media hash audit."}}

    def asset_board(self, project_id: str) -> dict[str, Any]:
        document = self.project_envelope(project_id)["document"]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for index, shot in enumerate(document.get("shots") or []):
            nodes.append({"id": f"shot:{shot['id']}", "node_type": "shot", "label": str(shot.get("purpose") or shot["id"]), "position": {"x": 40, "y": 100 + index * 140}, "shot_id": shot["id"], "config": {"status": shot.get("status")}, "status": str(shot.get("status") or "draft")})
        for index, asset in enumerate(document.get("assets") or []):
            nodes.append({"id": f"asset:{asset['id']}", "node_type": "asset", "label": str(asset.get("name") or asset["id"]), "position": {"x": 360, "y": 100 + index * 120}, "asset_id": asset["id"], "config": {"asset_class": asset.get("assetClass"), "required": bool(asset.get("required"))}, "status": str(asset.get("status") or "missing")})
        return {"project_id": project_id, "revision": 0, "board": {"version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": nodes, "edges": edges, "metadata": {"runtime_mode": "v5", "story_revision": self._revision(project_id), "asset_source_revision": self._revision(project_id)}}, "updated_at": document.get("updatedAt") or _now()}

    def story_envelope(self, project_id: str) -> dict[str, Any]:
        envelope = self.project_envelope(project_id)
        document = envelope["document"]
        story = {"spec": {"creative_goal": "", "audience": "", "platform": "", "duration": document.get("duration", 0), "ratio": document.get("ratio", "16:9"), "language": "", "brand_requirements": [], "must_preserve": [], "must_avoid": [], "structure": [], "beats": []}, "script": document.get("script", ""), "scenes": document.get("scenes", []), "shots": document.get("shots", []), "script_versions": [], "storyboard_versions": []}
        return {"project_id": project_id, "revision": envelope["revision"], "story": story, "checks": {"ok": True, "errors": 0, "warnings": 0, "issues": [], "metrics": {"scene_count": 0, "shot_count": len(story["shots"]), "total_duration": sum(float(shot.get("duration") or 0) for shot in story["shots"]), "target_duration": document.get("duration", 0)}}}

    def story_runs(self, project_id: str) -> dict[str, Any]:
        if self._project_row(project_id) is None:
            raise KeyError(project_id)
        return {"runs": []}

    def asset_audit(self, project_id: str) -> dict[str, Any]:
        library = self.asset_library(project_id)
        return {"project_id": project_id, "queue": "all", "items": [], "counts": {}, "total": 0, "summary": library["summary"]}

    def audio_studio(self, project_id: str) -> dict[str, Any]:
        envelope = self.project_envelope(project_id)
        return {"project_id": project_id, "revision": envelope["revision"], "document": {"version": 1, "voices": [], "voice_references": [], "auditions": [], "dialogues": [], "takes": [], "music_cues": [], "sound_design": [], "handoff": {"status": "draft", "approved_asset_ids": []}, "updated_at": envelope["updated_at"]}, "assets": [], "capabilities": {}, "audio_gates": {}, "workflow": {"router": "voice-controller", "voice": "voice-performance-director", "music": "music-sound-designer", "qa_owner": "voice-controller"}}

    def data_audit(self) -> dict[str, Any]:
        return {"ok": True, "schema_version": 22, "runtime_mode": "v5", "database": str(self.path), "counts": {table: len(self.store.list(table)) for table in ("projects", "sequences", "shots", "assets", "artifacts", "generations", "reviews")}, "failures": []}

    def legacy_shot(self, shot_id: str) -> dict[str, Any] | None:
        if self._legacy is None:
            raise LegacyReadOnlyError("FRAMEFLOW_LEGACY_READONLY_DB is not configured")
        return self._legacy.get_shot(shot_id)


__all__ = ["RuntimePersistence", "RuntimePersistenceError"]
