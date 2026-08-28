# FRAMEFLOW V5.3.2 — T03 Production Readiness Closure

Date: 2026-08-28
Branch: `dev/v5.3.2`
Failed cutover run: `T03FINAL-20260828T110620Z-817060f4`

## Result

The blocker `V5_HTTP_200_BUT_READY_FALSE` is closed in code and isolated
production-like testing. The failed production run itself was rolled back and
was not retried in this turn.

```text
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
READINESS CLOSURE = PASS
READY FOR ONE FINAL PRODUCTION CUTOVER RETRY = YES
```

The final line means only that the readiness closure gates are satisfied. This
turn did not authorize or execute a real production cutover.

## Root cause

Classification: `LEGACY_COMPAT_READINESS_FAILURE`.

The failing production V5 process successfully opened the V5 database and
served all P0 routes. However, `RuntimePersistence.health_payload()` returned
hard-coded `unbound`/`ready=false` capability entries with the reason
`Provider persistence is outside T03-R2`. It never read the already validated
provider profiles and capability bindings in the V5 startup config's
read-only Legacy archive.

The existing Legacy health contract required an enabled provider with a
successful last probe and an available bound model. The preserved archive had
an enabled healthy OpenCode orchestrator binding and an enabled healthy
Jimeng video binding. The old V5 facade discarded both, so the aggregate
predicate failed:

```text
orchestrator_capability_ready = false
media_capability_available = false
ready = false
```

This was permanent, not an async startup race. Candidate A had the same
condition; it passed only because the earlier smoke harness asserted HTTP 200,
runtime mode, route counts, and historical compatibility, but did not assert
`health.ready=true`.

The failed run directory contains the saved health/start-target/config and
database evidence, but no separate per-process stdout, stderr, lifespan, or
StateStore log files. The available lifecycle log was also inspected; it
records the V5 StartTarget event and does not add a competing failure. The
root cause is therefore established directly by the saved health payload and
the executed readiness code path, then confirmed by the isolated reproduction.

## Repair

- Added a shared readiness evaluator so Legacy and V5 use the same predicates.
- Added a read-only provider readiness projection from the preserved Legacy
  archive. Secrets are not read and no Legacy or V5 provider row is written.
- Added diagnostic `readiness.predicates`, `readiness.failing_predicates`, and
  `readiness_source` to V5 health evidence.
- Made the formal verification harness, mode-aware Python launcher, and
  PowerShell StartTarget path require V5 `ready=true`; a false readiness
  response now fails closed with the failing predicate reported.
- Added an explicit, isolated-only production-like simulation marker. It
  preserves `production=true` startup semantics while preventing a simulation
  from ever opening `data/frameflow.db`.

Detailed predicate evidence is in
`docs/T03_V5_PRODUCTION_READINESS_PREDICATE_MATRIX.md`.

## Isolated reproduction and certification

Original failed DB/config evidence was copied read-only to:

```text
data/.cutover/T03READINESS-20260828T112842Z-161ea33c/
```

Before the repair, the copied V5 DB reproduced the failure on a non-8787
port:

```text
first start: HTTP 200 / runtime_mode=v5 / status=not_ready / ready=false
restart:     HTTP 200 / runtime_mode=v5 / status=not_ready / ready=false
Workbench: 19/19
SH004-SH020: 17/17
```

The final clean production-like certification is recorded at:

```text
data/.cutover/T03READINESS-CERT-20260828T114614Z-23c7a59a/production-like-formal-evidence.json
```

It used `production=true` with an explicitly isolated V5 simulation database,
the same Legacy archive content, the formal `.venv` interpreter, and the same
Uvicorn server. Results:

```text
first health: ready=true, status=ready, runtime_mode=v5
first doctor DB: isolated v5-certification.db exact
first Workbench: 19 passed, 0 failed
first SH004-SH020: 17 passed, 0 failed
restart health: ready=true, status=ready, runtime_mode=v5
restart doctor DB: isolated v5-certification.db exact
restart Workbench: 19 passed, 0 failed
restart SH004-SH020: 17 passed, 0 failed
WAL: PASS
foreign keys: PASS
busy timeout: PASS (5000)
integrity: PASS (ok)
FK check: PASS (0)
Legacy archive: read-only validation PASS
production_cutover_performed: false
```

The real mode-aware launcher integration also passed with a live server and
the readiness gate enabled: `tests/runtime/test_v5_readiness.py::test_production_like_v5_start_and_restart_require_ready`.

Negative and positive dependency tests both passed:

```text
invalid orchestrator probe -> ready=false; failing_predicates=[orchestrator_capability_ready]
valid orchestrator + video probes -> ready=true; failing_predicates=[]
```

## Production safety

The canonical database was never opened by the V5 simulation and was not
replaced or intentionally migrated during this turn. The failed production run
remains historical evidence and its rollback remains preserved.

```text
Production DB replaced = NO
Production DB intentionally migrated = NO
Production schema = LEGACY_V3
Production tables = 41
Production integrity = PASS
Production FK = PASS
runtime-startup.json = ABSENT
Production runtime = LEGACY
Dual write = NO
Dual source = NO
```

## Regression gates

The focused closure suite passed 16 tests, including the real launcher
integration. Final regression counts were:

```text
lifecycle / cutover / handles / port subset: 37 passed, 0 failed, 0 errors, 0 blocked
schema / migration / runtime: 127 passed, 0 failed, 0 errors, 0 blocked
V3 regression: 37 passed, 0 failed
post-cutover DB contract: 1 passed, 0 failed
Git safety integration: 10 passed, 0 failed
full tests suite: 265 passed, 0 failed, 0 errors, 0 blocked
```

The complete test run emitted only the existing Starlette/httpx deprecation
warning. No production cutover was performed during any of these checks.
