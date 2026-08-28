"""Fail-closed production interpreter and formal-launcher cutover gates."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_VENV_ROOT = PROJECT_ROOT / ".venv"
FORMAL_PYTHON = FORMAL_VENV_ROOT / "Scripts" / "python.exe"
DEPENDENCY_MANIFEST = PROJECT_ROOT / "requirements.txt"
REQUIRED_RUNTIME_IMPORTS = (
    "jsonschema",
    "server",
    "core.runtime.persistence",
    "core.runtime.persistence.startup_config",
    "core.runtime.state_store",
    "core.runtime.state_store.factory",
    "core.migration.legacy_compat",
    "scripts.migrate_shot_spec_v1_to_v2_2",
)
FORMAL_LAUNCHER_EVIDENCE_VERSION = 1


class ProductionEnvironmentError(RuntimeError):
    """Raised before swap when the formal production environment is unsafe."""


def declared_jsonschema_version(path: Path | str = DEPENDENCY_MANIFEST) -> str:
    manifest = Path(path).expanduser().resolve(strict=False)
    if not manifest.is_file():
        raise ProductionEnvironmentError(f"dependency manifest does not exist: {manifest}")
    match = re.search(
        r"(?im)^\s*jsonschema\s*==\s*([^\s#]+)\s*(?:#.*)?$",
        manifest.read_text(encoding="utf-8"),
    )
    if match is None:
        raise ProductionEnvironmentError(
            f"jsonschema must be exactly declared in {manifest}"
        )
    return match.group(1)


def _runtime_import_script() -> str:
    modules = repr(REQUIRED_RUNTIME_IMPORTS)
    return (
        "import importlib,importlib.metadata,json,platform,sys;"
        f"mods={modules};"
        "[importlib.import_module(name) for name in mods];"
        "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,"
        "'base_prefix':sys.base_prefix,'version':platform.python_version(),"
        "'version_info':list(sys.version_info[:3]),'imports':list(mods),"
        "'jsonschema':importlib.metadata.version('jsonschema')}))"
    )


def inspect_interpreter(interpreter: Path | str) -> dict[str, Any]:
    resolved = Path(interpreter).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise ProductionEnvironmentError(f"production interpreter does not exist: {resolved}")
    completed = subprocess.run(
        [str(resolved), "-c", _runtime_import_script()],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ProductionEnvironmentError(
            "production runtime import smoke failed before swap: "
            f"interpreter={resolved} stderr={completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ProductionEnvironmentError(
            f"production interpreter returned invalid identity evidence: {resolved}"
        ) from exc
    payload["returncode"] = completed.returncode
    return payload


def verify_production_interpreter(
    interpreter: Path | str = FORMAL_PYTHON,
) -> dict[str, Any]:
    """Verify identity, imports, declaration, and dependency consistency."""

    resolved = Path(interpreter).expanduser().resolve(strict=False)
    expected = FORMAL_PYTHON.resolve(strict=False)
    if resolved != expected:
        raise ProductionEnvironmentError(
            f"wrong production interpreter: expected={expected} actual={resolved}"
        )
    identity = inspect_interpreter(resolved)
    prefix = Path(str(identity["prefix"])).resolve(strict=False)
    if prefix != FORMAL_VENV_ROOT.resolve(strict=False):
        raise ProductionEnvironmentError(
            f"production interpreter prefix is outside project .venv: {prefix}"
        )
    version_info = tuple(int(value) for value in identity["version_info"])
    if not ((3, 11) <= version_info < (3, 15)):
        raise ProductionEnvironmentError(
            f"unsupported production Python version: {identity['version']}"
        )
    declared = declared_jsonschema_version()
    if identity["jsonschema"] != declared:
        raise ProductionEnvironmentError(
            "formal .venv jsonschema does not match requirements.txt: "
            f"declared={declared} installed={identity['jsonschema']}"
        )
    dependency_check = subprocess.run(
        [str(resolved), "-m", "pip", "check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if dependency_check.returncode != 0:
        raise ProductionEnvironmentError(
            f"formal .venv dependency check failed: {dependency_check.stdout}{dependency_check.stderr}"
        )
    manifest_check = subprocess.run(
        [
            str(resolved),
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--no-index",
            "--disable-pip-version-check",
            "-r",
            str(DEPENDENCY_MANIFEST.resolve(strict=False)),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if manifest_check.returncode != 0:
        raise ProductionEnvironmentError(
            "formal .venv is not synchronized with requirements.txt: "
            f"{manifest_check.stdout}{manifest_check.stderr}"
        )
    return {
        "passed": True,
        "interpreter": str(resolved),
        "venv_root": str(FORMAL_VENV_ROOT.resolve(strict=False)),
        "identity": identity,
        "dependency_manifest": str(DEPENDENCY_MANIFEST.resolve(strict=False)),
        "jsonschema_declared": declared,
        "jsonschema_installed": identity["jsonschema"],
        "pip_check": dependency_check.stdout.strip(),
        "manifest_check": "PASS",
    }


def verify_formal_launcher_evidence(
    evidence: Mapping[str, Any] | None,
    *,
    candidate: Path | str,
    legacy_archive: Path | str,
) -> dict[str, Any]:
    """Require complete two-boot formal-launcher proof before any DB swap."""

    if evidence is None:
        raise ProductionEnvironmentError(
            "formal production launcher pre-swap evidence is required"
        )
    if int(evidence.get("formal_launcher_evidence_version") or 0) != FORMAL_LAUNCHER_EVIDENCE_VERSION:
        raise ProductionEnvironmentError("unsupported formal launcher evidence version")
    if evidence.get("status") != "PASS":
        raise ProductionEnvironmentError("formal production launcher probe did not pass")
    expected_candidate = Path(candidate).expanduser().resolve(strict=False)
    expected_archive = Path(legacy_archive).expanduser().resolve(strict=False)
    if Path(str(evidence.get("candidate") or "")).resolve(strict=False) != expected_candidate:
        raise ProductionEnvironmentError("formal launcher evidence candidate mismatch")
    if Path(str(evidence.get("legacy") or "")).resolve(strict=False) != expected_archive:
        raise ProductionEnvironmentError("formal launcher evidence archive mismatch")
    interpreter_gate = evidence.get("interpreter_gate")
    if not isinstance(interpreter_gate, Mapping) or interpreter_gate.get("passed") is not True:
        raise ProductionEnvironmentError("production interpreter gate did not pass")
    if Path(str(interpreter_gate.get("interpreter") or "")).resolve(strict=False) != FORMAL_PYTHON.resolve(strict=False):
        raise ProductionEnvironmentError("formal launcher used the wrong interpreter")
    launcher = evidence.get("formal_launcher_command")
    if not isinstance(launcher, list) or len(launcher) < 4:
        raise ProductionEnvironmentError("formal launcher command evidence is missing")
    if Path(str(launcher[0])).resolve(strict=False) != FORMAL_PYTHON.resolve(strict=False):
        raise ProductionEnvironmentError("formal launcher command used the wrong interpreter")
    if launcher[1:4] != ["-m", "uvicorn", "server:app"]:
        raise ProductionEnvironmentError("formal launcher command is not the production Uvicorn entrypoint")
    config = evidence.get("runtime_config_payload")
    if not isinstance(config, Mapping) or config.get("runtime_mode") != "v5":
        raise ProductionEnvironmentError("formal launcher runtime config evidence is missing")
    if Path(str(config.get("runtime_db") or "")).resolve(strict=False) != expected_candidate:
        raise ProductionEnvironmentError("formal launcher runtime config candidate mismatch")
    if Path(str(config.get("legacy_readonly_db") or "")).resolve(strict=False) != expected_archive:
        raise ProductionEnvironmentError("formal launcher runtime config archive mismatch")
    if evidence.get("ownership_environment_fields_injected") != []:
        raise ProductionEnvironmentError("formal launcher probe injected runtime ownership fields")
    cleanup = evidence.get("probe_fixture_cleanup")
    if not isinstance(cleanup, Mapping) or cleanup.get("passed") is not True or cleanup.get("remaining") != []:
        raise ProductionEnvironmentError("formal launcher probe fixture cleanup did not pass")
    stabilization = evidence.get("final_stabilization")
    if not isinstance(stabilization, Mapping):
        raise ProductionEnvironmentError("formal launcher final stabilization evidence is missing")
    if stabilization.get("backend_stopped") is not True:
        raise ProductionEnvironmentError("formal launcher backend shutdown was not proven")
    port_free = stabilization.get("port_free")
    if not isinstance(port_free, Mapping) or port_free.get("free") is not True:
        raise ProductionEnvironmentError("formal launcher isolated port was not proven free")
    checkpoint = stabilization.get("checkpoint")
    checkpoint_rows = checkpoint.get("checkpoint") if isinstance(checkpoint, Mapping) else None
    if not isinstance(checkpoint_rows, list) or any(
        not isinstance(row, (list, tuple)) or not row or int(row[0]) != 0
        for row in checkpoint_rows
    ):
        raise ProductionEnvironmentError("formal launcher final WAL checkpoint did not pass")
    stable_samples = stabilization.get("stable_samples")
    final_file_state = stabilization.get("final_file_state")
    if not isinstance(stable_samples, list) or len(stable_samples) < 3 or not isinstance(final_file_state, Mapping):
        raise ProductionEnvironmentError("formal launcher final stable file evidence is missing")
    for sidecar in ("wal", "shm"):
        sidecar_state = final_file_state.get(sidecar)
        if not isinstance(sidecar_state, Mapping) or sidecar_state.get("exists") is True:
            raise ProductionEnvironmentError(f"formal launcher final {sidecar} sidecar remains")
    expected_sha = str(evidence.get("candidate_sha256_after_probe") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ProductionEnvironmentError("formal launcher candidate fingerprint evidence is missing")
    if str(stabilization.get("final_candidate_sha256") or "") != expected_sha:
        raise ProductionEnvironmentError("formal launcher final stabilization SHA is inconsistent")
    actual_digest = hashlib.sha256()
    with expected_candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            actual_digest.update(chunk)
    if actual_digest.hexdigest() != expected_sha:
        raise ProductionEnvironmentError("candidate changed after formal launcher probe")
    boots = evidence.get("boots")
    if not isinstance(boots, list) or len(boots) != 2:
        raise ProductionEnvironmentError("formal launcher first-start and restart evidence are required")
    for expected_name, boot in zip(("first_start", "restart"), boots, strict=True):
        if not isinstance(boot, Mapping) or boot.get("boot") != expected_name:
            raise ProductionEnvironmentError(f"missing formal launcher {expected_name} evidence")
        if boot.get("api_passed") != 19 or boot.get("api_failed") != 0:
            raise ProductionEnvironmentError(f"formal launcher {expected_name} 19-API gate failed")
        if boot.get("historical_passed") != 17 or boot.get("historical_failed") != 0:
            raise ProductionEnvironmentError(f"formal launcher {expected_name} historical gate failed")
        health = boot.get("health")
        if (
            not isinstance(health, Mapping)
            or health.get("runtime_mode") != "v5"
            or health.get("ready") is not True
        ):
            raise ProductionEnvironmentError(f"formal launcher {expected_name} health gate failed")
    return dict(evidence)


__all__ = [
    "DEPENDENCY_MANIFEST",
    "FORMAL_LAUNCHER_EVIDENCE_VERSION",
    "FORMAL_PYTHON",
    "FORMAL_VENV_ROOT",
    "ProductionEnvironmentError",
    "REQUIRED_RUNTIME_IMPORTS",
    "declared_jsonschema_version",
    "inspect_interpreter",
    "verify_formal_launcher_evidence",
    "verify_production_interpreter",
]
