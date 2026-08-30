"""T04 plan/apply artifact retention with compensation.

Retention is intentionally independent from startup and task orchestration.
The only database mutation in Apply is the same-transaction update of the
affected Artifact rows' path and status.  No task, event, generation, review,
provider, or resource-lock rows are changed.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import select, update

from core.schemas.runtime_mvp import metadata


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_APPROVED_DECISIONS = frozenset({"APPROVED", "QA_APPROVED"})
_APPROVED_GENERATION_STATUSES = frozenset({"APPROVED", "QA_APPROVED"})
_FORBIDDEN_ROOTS = (Path(r"D:\AIGC\SUYU"), Path(r"D:\ComfyUI"))


class RetentionError(RuntimeError):
    """An error that must fail closed during planning or applying."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class RetentionPolicy:
    keep_last_generations_per_shot: int = 2
    never_delete_locked_asset_master: bool = True
    never_delete_approved_generation: bool = True
    max_archive_size_gb: float | None = None

    def __post_init__(self) -> None:
        if self.keep_last_generations_per_shot < 0:
            raise ValueError("keep_last_generations_per_shot must be non-negative")
        if self.max_archive_size_gb is not None and self.max_archive_size_gb < 0:
            raise ValueError("max_archive_size_gb must be non-negative")


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_id(value: Any, field: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text):
        raise RetentionError("UNSAFE_IDENTIFIER", f"{field} is not a safe archive path component.", {field: text})
    return text


def _timestamp(value: Any) -> float:
    if value is None:
        return float("-inf")
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_approved(review_rows: Iterable[Mapping[str, Any]], generation: Mapping[str, Any]) -> tuple[bool, str | None]:
    reviews = sorted(
        (row for row in review_rows if row.get("generation_id") == generation.get("id")),
        key=lambda row: (_timestamp(row.get("created_at")), str(row.get("id") or "")),
        reverse=True,
    )
    if reviews:
        latest_time = _timestamp(reviews[0].get("created_at"))
        tied = [row for row in reviews if _timestamp(row.get("created_at")) == latest_time]
        decisions = {str(row.get("decision") or "").strip().upper() for row in tied}
        if len(decisions) > 1:
            return False, "approval_review_ambiguous"
        return bool(decisions & _APPROVED_DECISIONS), None
    if str(generation.get("status") or "").strip().upper() in _APPROVED_GENERATION_STATUSES:
        return False, "approved_status_without_canonical_review"
    return False, None


class RetentionService:
    """Build dry-run retention plans and apply them conservatively."""

    def __init__(
        self,
        store: Any,
        *,
        projects_root: Path | str | None = None,
        archive_root: Path | str | None = None,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self.store = store
        self.projects_root = (
            Path(projects_root).resolve(strict=False)
            if projects_root is not None
            else (Path(store.path).parent / "projects").resolve(strict=False)
        )
        self.archive_root = (
            Path(archive_root).resolve(strict=False)
            if archive_root is not None
            else (self.projects_root.parent.parent / "archives").resolve(strict=False)
        )
        self.policy = policy or RetentionPolicy()

    def project_root(self, project_id: str) -> Path:
        project_id = _safe_id(project_id, "project_id")
        return (self.projects_root / project_id).resolve(strict=False)

    def archive_generation_root(self, project_id: str, shot_id: str, generation_id: str) -> Path:
        project_id = _safe_id(project_id, "project_id")
        shot_id = _safe_id(shot_id, "shot_id")
        generation_id = _safe_id(generation_id, "generation_id")
        root = (self.archive_root / project_id / shot_id / generation_id).resolve(strict=False)
        if not _within(root, self.archive_root):
            raise RetentionError("ARCHIVE_PATH_ESCAPE", "Archive destination escaped archive root.")
        return root

    def _source_path(self, project_id: str, raw_path: str) -> tuple[Path, str | None]:
        project_root = self.project_root(project_id)
        raw = Path(raw_path)
        if raw.is_absolute():
            candidate = raw
        elif raw.parts and raw.parts[0].casefold() == "projects":
            candidate = self.projects_root.parent / raw
        elif raw.parts and raw.parts[0].casefold() == project_id.casefold():
            candidate = self.projects_root / raw
        else:
            candidate = project_root / raw
        resolved = candidate.resolve(strict=False)
        if candidate.exists() and candidate.is_symlink():
            return resolved, "source_symlink"
        if not _within(resolved, project_root):
            return resolved, "source_outside_project_root"
        if _within(resolved, self.archive_root):
            return resolved, "source_is_archive"
        for forbidden in _FORBIDDEN_ROOTS:
            if _within(resolved, forbidden.resolve(strict=False)):
                return resolved, "source_forbidden_legacy_root"
        if not resolved.exists():
            return resolved, "source_missing"
        if not resolved.is_file():
            return resolved, "source_not_file"
        return resolved, None

    @staticmethod
    def _generation_directory(source: Path, generation_id: str) -> Path | None:
        if source.parent.name.casefold() == generation_id.casefold():
            return source.parent
        parts = source.parts
        for index, part in enumerate(parts[:-1]):
            if part.casefold() == "generations" and parts[index + 1].casefold() == generation_id.casefold():
                return Path(source.anchor).joinpath(*parts[1 : index + 2])
        return None

    def _destination(self, project_id: str, shot_id: str, generation_id: str, source: Path) -> Path:
        root = self.archive_generation_root(project_id, shot_id, generation_id)
        destination = (root / source.name).resolve(strict=False)
        if destination.parent != root or not _within(destination, self.archive_root):
            raise RetentionError("ARCHIVE_PATH_ESCAPE", "Artifact destination escaped generation archive root.")
        return destination

    def _artifact_entry(
        self,
        project_id: str,
        shot_id: str,
        generation_id: str,
        row: Mapping[str, Any],
        *,
        archive_destination: Path,
    ) -> dict[str, Any]:
        raw_path = str(row.get("path") or "")
        source, reason = self._source_path(project_id, raw_path)
        destination = self._destination(project_id, shot_id, generation_id, source)
        size = source.stat().st_size if reason is None else None
        already_archived = (
            str(row.get("status") or "").upper() == "ARCHIVED"
            and _within(source, archive_destination)
            and source.is_file()
        )
        if reason is None and not already_archived and (destination.exists() or destination.is_symlink()):
            reason = "destination_collision"
        return {
            "artifact_id": str(row.get("id")),
            "original_path": raw_path,
            "source_path": str(source),
            "destination_path": str(destination),
            "sha256": row.get("sha256"),
            "size_bytes": size,
            "status": row.get("status"),
            "source_reason": reason,
            "already_archived": already_archived,
        }

    def _load_rows(self) -> dict[str, list[dict[str, Any]]]:
        table = metadata.tables
        with self.store.connection() as connection:
            rows: dict[str, list[dict[str, Any]]] = {}
            for name in ("projects", "sequences", "shots", "assets", "artifacts", "generations", "reviews"):
                rows[name] = [dict(row) for row in connection.execute(select(table[name])).mappings().all()]
        return rows

    def _archive_size_bytes(self) -> int:
        if not self.archive_root.is_dir():
            return 0
        total = 0
        for project_dir in self.archive_root.iterdir():
            if project_dir.name.casefold() == "migrations" or project_dir.is_symlink() or not project_dir.is_dir():
                continue
            for path in project_dir.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _size_report(self, current_bytes: int, projected_bytes: int) -> dict[str, Any]:
        threshold = self.policy.max_archive_size_gb
        if threshold is None:
            return {
                "current_bytes": current_bytes,
                "projected_bytes": projected_bytes,
                "threshold_gb": None,
                "threshold_status": "not_configured",
                "warning_code": "ARCHIVE_SIZE_THRESHOLD_DECISION_REQUIRED",
            }
        exceeded = projected_bytes > threshold * 1024**3
        return {
            "current_bytes": current_bytes,
            "projected_bytes": projected_bytes,
            "threshold_gb": threshold,
            "threshold_status": "warning" if exceeded else "ok",
            "warning_code": "ARCHIVE_SIZE_THRESHOLD_EXCEEDED" if exceeded else None,
        }

    def plan(self, project_id: str | None = None) -> dict[str, Any]:
        rows = self._load_rows()
        projects = {str(row["id"]): row for row in rows["projects"]}
        shots = {str(row["id"]): row for row in rows["shots"]}
        assets = rows["assets"]
        artifacts = rows["artifacts"]
        generations = rows["generations"]
        reviews = rows["reviews"]
        if project_id is not None:
            project_id = _safe_id(project_id, "project_id")
            generation_scope = [
                row for row in generations
                if str(shots.get(str(row.get("shot_id")), {}).get("project_id")) == project_id
            ]
        else:
            generation_scope = [
                row for row in generations
                if str(shots.get(str(row.get("shot_id")), {}).get("project_id")) in projects
            ]

        artifacts_by_id = {str(row["id"]): row for row in artifacts}
        units: list[dict[str, Any]] = []
        projected_bytes = self._archive_size_bytes()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for generation in generation_scope:
            shot = shots.get(str(generation.get("shot_id")))
            if shot is None:
                continue
            grouped.setdefault(str(shot.get("id")), []).append(generation)

        for shot_id, shot_generations in grouped.items():
            shot_generations.sort(
                key=lambda row: (_timestamp(row.get("created_at")), str(row.get("id") or "")),
                reverse=True,
            )
            for index, generation in enumerate(shot_generations):
                generation_id = str(generation.get("id"))
                pid = str(shots[shot_id].get("project_id"))
                package_id = str(generation.get("package_manifest_artifact_id") or "")
                package = artifacts_by_id.get(package_id)
                archive_root = self.archive_generation_root(pid, shot_id, generation_id)

                # An already applied unit is recognized only when every known
                # artifact in the canonical generation directory is archived.
                # This prevents a partial prior update from silently reducing
                # a multi-file generation to its package manifest only.
                expected_source_root = (
                    self.project_root(pid) / "shots" / shot_id / "generations" / generation_id
                ).resolve(strict=False)
                generation_related = [
                    row for row in artifacts
                    if str(row.get("project_id")) == pid
                    and (
                        _within(Path(str(row.get("path") or "")).resolve(strict=False), expected_source_root)
                        or _within(Path(str(row.get("path") or "")).resolve(strict=False), archive_root)
                    )
                ]
                archived_candidates = [
                    row for row in artifacts
                    if str(row.get("project_id")) == pid
                    and str(row.get("status") or "").upper() == "ARCHIVED"
                    and str(row.get("path") or "")
                    and _within(Path(str(row["path"])).resolve(strict=False), archive_root)
                ]
                if package is not None and package in archived_candidates:
                    related_ids = {str(row.get("id")) for row in generation_related}
                    related_ids.add(package_id)
                    fully_archived = all(
                        str(row.get("status") or "").upper() == "ARCHIVED"
                        and _within(Path(str(row.get("path") or "")).resolve(strict=False), archive_root)
                        for row in artifacts
                        if str(row.get("id")) in related_ids
                    )
                    if fully_archived:
                        entries = [
                            self._artifact_entry(pid, shot_id, generation_id, row, archive_destination=archive_root)
                            for row in artifacts
                            if str(row.get("id")) in related_ids
                        ]
                        if all(entry["already_archived"] for entry in entries):
                            units.append({
                                "project_id": pid,
                                "shot_id": shot_id,
                                "generation_id": generation_id,
                                "action": "already_archived",
                                "reasons": ["already_archived"],
                                "artifacts": entries,
                            })
                            continue
                    else:
                        units.append({
                            "project_id": pid,
                            "shot_id": shot_id,
                            "generation_id": generation_id,
                            "action": "protect",
                            "reasons": ["partial_archive"],
                            "artifacts": [],
                        })
                        continue

                if package is None:
                    units.append({
                        "project_id": pid,
                        "shot_id": shot_id,
                        "generation_id": generation_id,
                        "action": "protect",
                        "reasons": ["manifest_artifact_missing"],
                        "artifacts": [],
                    })
                    continue

                package_source, package_reason = self._source_path(pid, str(package.get("path") or ""))
                generation_dir = (
                    self._generation_directory(package_source, generation_id)
                    if package_reason is None
                    else None
                )
                unit_rows = [package]
                if generation_dir is not None:
                    for artifact in artifacts:
                        if str(artifact.get("project_id")) != pid or str(artifact.get("id")) == package_id:
                            continue
                        source, reason = self._source_path(pid, str(artifact.get("path") or ""))
                        if reason is None and _within(source, generation_dir):
                            unit_rows.append(artifact)
                        elif reason is not None and str(artifact.get("path") or ""):
                            # An artifact recorded inside a generation unit
                            # cannot be silently split from the unit.
                            raw = Path(str(artifact.get("path")))
                            if raw.parent == generation_dir or str(generation_id).casefold() in {part.casefold() for part in raw.parts}:
                                unit_rows.append(artifact)
                unique_rows = {str(row.get("id")): row for row in unit_rows}
                destination_names: set[str] = set()
                entries = []
                for artifact in unique_rows.values():
                    entry = self._artifact_entry(pid, shot_id, generation_id, artifact, archive_destination=archive_root)
                    if entry["destination_path"].casefold() in destination_names:
                        entry["source_reason"] = "destination_name_collision"
                    destination_names.add(entry["destination_path"].casefold())
                    entries.append(entry)

                reasons: list[str] = []
                approved, approval_reason = _is_approved(reviews, generation)
                if approved and self.policy.never_delete_approved_generation:
                    reasons.append("approved_generation")
                elif approval_reason:
                    reasons.append(approval_reason)
                masters = {
                    str(asset.get("master_artifact_id"))
                    for asset in assets
                    if str(asset.get("status") or "").upper() == "LOCKED" and asset.get("master_artifact_id")
                }
                if self.policy.never_delete_locked_asset_master and masters.intersection(unique_rows):
                    reasons.append("locked_asset_master")
                if index < self.policy.keep_last_generations_per_shot:
                    reasons.append("keep_last_generations")
                reasons.extend(
                    sorted(
                        {
                            str(entry["source_reason"])
                            for entry in entries
                            if entry.get("source_reason") and entry.get("source_reason") != "source_is_archive"
                        }
                    )
                )
                if any(name == "destination_name_collision" for name in (entry.get("source_reason") for entry in entries)):
                    reasons.append("destination_name_collision")

                unique_reasons = list(dict.fromkeys(reasons))
                action = "protect" if unique_reasons else "archive"
                if action == "archive":
                    projected_bytes += sum(int(entry["size_bytes"] or 0) for entry in entries)
                units.append({
                    "project_id": pid,
                    "shot_id": shot_id,
                    "generation_id": generation_id,
                    "created_at": generation.get("created_at"),
                    "action": action,
                    "reasons": unique_reasons,
                    "artifacts": entries,
                })

        size = self._size_report(self._archive_size_bytes(), projected_bytes)
        return {
            "status": "PLANNED",
            "dry_run": True,
            "policy": asdict(self.policy),
            "project_id": project_id,
            "units": units,
            "archive_size": size,
            "warnings": [size["warning_code"]] if size["warning_code"] else [],
            "apply_allowed": True,
        }

    def plan_retention(self, project_id: str | None = None) -> dict[str, Any]:
        return self.plan(project_id)

    def _verify_moved_files(self, entries: list[Mapping[str, Any]]) -> None:
        if not entries:
            raise RetentionError("EMPTY_RETENTION_UNIT", "A generation retention unit has no artifacts.")
        for entry in entries:
            destination = Path(str(entry["destination_path"]))
            if not destination.is_file():
                raise RetentionError("DESTINATION_VERIFICATION_FAILED", "Moved artifact is missing at destination.", {"path": str(destination)})
            expected_size = entry.get("size_bytes")
            if expected_size is not None and destination.stat().st_size != int(expected_size):
                raise RetentionError("DESTINATION_VERIFICATION_FAILED", "Moved artifact size changed.", {"path": str(destination)})
            actual = _sha256(destination)
            expected_hash = str(entry.get("sha256") or "").strip().lower()
            if expected_hash and actual != expected_hash:
                raise RetentionError("DESTINATION_VERIFICATION_FAILED", "Moved artifact hash changed.", {"path": str(destination)})

    def _commit_archive_metadata(self, entries: list[Mapping[str, Any]]) -> None:
        table = metadata.tables["artifacts"]
        with self.store.transaction(immediate=True) as connection:
            for entry in entries:
                artifact_id = str(entry["artifact_id"])
                current = connection.execute(
                    select(table).where(table.c.id == artifact_id)
                ).mappings().first()
                if current is None or str(current.get("path")) != str(entry["original_path"]):
                    raise RetentionError("PLAN_STALE", "Artifact changed after retention planning.", {"artifact_id": artifact_id})
                if str(current.get("status") or "").upper() == "ARCHIVED":
                    raise RetentionError("PLAN_STALE", "Artifact is already archived.", {"artifact_id": artifact_id})
                result = connection.execute(
                    update(table)
                    .where(table.c.id == artifact_id)
                    .values(path=str(entry["destination_path"]), status="ARCHIVED")
                )
                if result.rowcount != 1:
                    raise RetentionError("DATABASE_UPDATE_FAILED", "Artifact metadata update affected an unexpected row count.", {"artifact_id": artifact_id})

    @staticmethod
    def _compensate(moved: list[tuple[Path, Path]]) -> None:
        failures: list[str] = []
        for destination, source in reversed(moved):
            try:
                if not destination.exists():
                    raise OSError("destination disappeared")
                if source.exists():
                    raise OSError("source path is occupied")
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, source)
                if not source.is_file():
                    raise OSError("source was not restored")
            except Exception as exc:  # pragma: no cover - exercised by injected failures
                failures.append(f"{destination} -> {source}: {exc}")
        if failures:
            raise RetentionError("RETENTION_COMPENSATION_FAILED", "Retention compensation could not restore all sources.", {"failures": failures})

    @staticmethod
    def _cleanup_created_dirs(created_dirs: list[Path]) -> None:
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass

    def _apply_unit(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        pid = str(unit["project_id"])
        shot_id = str(unit["shot_id"])
        generation_id = str(unit["generation_id"])
        fresh = self.plan(pid)
        current = next((item for item in fresh["units"] if item.get("generation_id") == generation_id), None)
        if current is not None and current.get("action") == "already_archived":
            return {"status": "already_archived", "generation_id": generation_id}
        if current is None or current.get("action") != "archive":
            return {"status": "FAILED", "code": "PLAN_STALE", "generation_id": generation_id}
        entries = list(current.get("artifacts") or [])
        destination_root = self.archive_generation_root(pid, shot_id, generation_id)
        for entry in entries:
            if entry.get("source_reason"):
                return {"status": "FAILED", "code": str(entry["source_reason"]), "generation_id": generation_id}
            destination = Path(str(entry["destination_path"]))
            if destination.exists() or destination.is_symlink():
                return {"status": "FAILED", "code": "DESTINATION_COLLISION", "generation_id": generation_id, "path": str(destination)}

        created_dirs: list[Path] = []
        moved: list[tuple[Path, Path]] = []
        try:
            for directory in (
                self.archive_root,
                self.archive_root / pid,
                self.archive_root / pid / shot_id,
                destination_root,
            ):
                directory = directory.resolve(strict=False)
                if not _within(directory, self.archive_root):
                    raise RetentionError("ARCHIVE_PATH_ESCAPE", "Archive directory escaped archive root.")
                if directory.exists():
                    if not directory.is_dir() or directory.is_symlink():
                        raise RetentionError("DESTINATION_COLLISION", "Archive path is not a normal directory.", {"path": str(directory)})
                else:
                    directory.mkdir()
                    created_dirs.append(directory)
            for entry in entries:
                source = Path(str(entry["source_path"]))
                destination = Path(str(entry["destination_path"]))
                os.replace(source, destination)
                moved.append((destination, source))
            self._verify_moved_files(entries)
            self._commit_archive_metadata(entries)
            return {
                "status": "ARCHIVED",
                "generation_id": generation_id,
                "artifact_ids": [str(entry["artifact_id"]) for entry in entries],
                "archive_root": str(destination_root),
            }
        except Exception as exc:
            compensation_error: RetentionError | None = None
            if moved:
                try:
                    self._compensate(moved)
                except RetentionError as restore_error:
                    compensation_error = restore_error
            self._cleanup_created_dirs(created_dirs)
            if compensation_error is not None:
                return {
                    "status": "RETENTION_COMPENSATION_FAILED",
                    "code": compensation_error.code,
                    "generation_id": generation_id,
                    "error": str(exc),
                    "details": compensation_error.details,
                }
            code = exc.code if isinstance(exc, RetentionError) else "RETENTION_APPLY_FAILED"
            return {"status": "FAILED", "code": code, "generation_id": generation_id, "error": str(exc)}

    def apply(self, plan: Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        # ``dry_run`` on the plan records that planning is side-effect free;
        # it must not make a reviewed plan impossible to Apply.  Callers who
        # explicitly request an Apply preview use the method argument.
        if dry_run:
            return {"status": "DRY_RUN", "dry_run": True, "applied": [], "failed": []}
        if plan.get("status") != "PLANNED":
            raise RetentionError("INVALID_RETENTION_PLAN", "Only a PLANNED retention plan may be applied.")
        results: list[dict[str, Any]] = []
        for unit in plan.get("units") or []:
            if unit.get("action") != "archive":
                continue
            result = self._apply_unit(unit)
            results.append(result)
            if result.get("status") not in {"ARCHIVED", "already_archived"}:
                break
        failed = [result for result in results if result.get("status") not in {"ARCHIVED", "already_archived"}]
        return {
            "status": "FAILED" if failed else "APPLIED",
            "dry_run": False,
            "applied": [result for result in results if result.get("status") == "ARCHIVED"],
            "failed": failed,
        }

    def apply_retention(self, plan: Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        return self.apply(plan, dry_run=dry_run)


__all__ = ["RetentionError", "RetentionPolicy", "RetentionService"]
