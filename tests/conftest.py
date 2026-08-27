"""Windows-safe test environment for FRAMEFLOW runtime tests.

The host's user TEMP directory can contain inherited ACLs that prevent a
SQLite database from being opened inside a newly-created TemporaryDirectory.
Keep test-only temporary state inside the repository's writable workspace and
make the setting visible to subprocesses as well.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_TMP = PROJECT_ROOT / ".tmp" / "tests"
TEST_TMP = Path(os.environ.get("FRAMEFLOW_TEST_TMP") or DEFAULT_TEST_TMP).expanduser().resolve(
    strict=False
)
TEST_TMP.mkdir(parents=True, exist_ok=True)

# tempfile caches the resolved directory after the first gettempdir() call;
# set both the cache and the environment before test modules are imported.
os.environ["FRAMEFLOW_TEST_TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
os.environ["TMP"] = str(TEST_TMP)
tempfile.tempdir = str(TEST_TMP)
