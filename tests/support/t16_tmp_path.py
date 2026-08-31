"""Workspace-local replacement for pytest's host-ACL-sensitive tmp_path.

Loaded only by the explicit T16 regression command with ``-p no:tmpdir``.
It keeps every test fixture below the ignored workspace `.tmp` directory and
does not alter normal test-suite behavior.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture()
def tmp_path(request: pytest.FixtureRequest) -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "t16-regression" / request.node.name / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root
