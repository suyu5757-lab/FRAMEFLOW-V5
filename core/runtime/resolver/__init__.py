"""T20 deterministic, read-only Shot resolver."""

from .shot_resolver import (
    ResolutionIssue,
    ResolvedArtifact,
    ResolvedAsset,
    ResolvedShotContext,
    ShotResolver,
    resolve_shot,
)

__all__ = [
    "ResolutionIssue",
    "ResolvedArtifact",
    "ResolvedAsset",
    "ResolvedShotContext",
    "ShotResolver",
    "resolve_shot",
]
