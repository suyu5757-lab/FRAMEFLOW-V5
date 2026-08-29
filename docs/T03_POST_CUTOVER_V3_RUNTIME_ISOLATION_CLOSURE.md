# T03 post-cutover V3 runtime/app isolation closure

Date: 2026-08-29
Production cutover: **NOT PERFORMED**
Production state: `LEGACY_V3` throughout this closure

## Verdict

The post-cutover V3 failure was a test-harness isolation defect. V5 was
correctly returning `501 v5_route_not_implemented` for retired V3 write
routes. The Legacy regression harness now owns its database, runtime config,
runtime mode, FastAPI app, persistence lifecycle, module namespace, and
network boundary.

The exact post-cutover sequence was reproduced with an isolated V5 database
and an isolated runtime-startup document. V3 passed 37/37 while that V5
runtime remained active; the V5 logical fingerprint and runtime config were
unchanged afterwards. The full suite passed 281/281.

## Exact failure trace

The first deterministic failure was:

```text
test = FrameflowV3Tests.test_agent_patch_preview_rejects_locked_node_and_revision_conflict
fixture = FrameflowV3Tests.setUp (historical pre-fix implementation)
DB path = D:\\11067\\CodexWorkspaces\\frameflow-v3\\tests\\test-v3-<uuid>.db
FRAMEFLOW_RUNTIME_CONFIG = not set by the V3 fixture; the ambient/default resolver remained active
runtime config path = D:\\11067\\CodexWorkspaces\\frameflow-v3\\data\\runtime-startup.json
runtime config payload mode = v5, production=true, runtime_db=data\\frameflow.db
server/app object = the process-global server.app imported while the V5 production config was active
RuntimePersistence object = server.app.state.persistence created for that cached V5 app
expected runtime_mode = legacy
actual runtime_mode = v5
501 callsite = server.py:367-371
exact leak origin = the fixture patched only server.DB_PATH, then reused server.app;
                  RUNTIME_ENVIRONMENT and RUNTIME_MODE had already been resolved and cached at import
```

The path and config values above are the effective values proven by the
preserved rollback classification and by the reproduction. The old fixture
did not own `FRAMEFLOW_RUNTIME_CONFIG`; therefore when the real production
startup document existed, `resolve_runtime_environment()` selected it through
the default path.

The boundaries are visible in the current source:

- `core/runtime/persistence/startup_config.py:166-190` resolves the explicit
  config or, when no explicit value is supplied, the repository default.
- `server.py:47-49` caches `RUNTIME_ENVIRONMENT`, `DB_PATH`, and
  `RUNTIME_MODE` during module import.
- `server.py:197-204` creates and attaches V5 `RuntimePersistence` to the
  app during lifespan startup.
- `server.py:367-371` intentionally returns `501` for a non-GET V3 project
  route in V5 mode.
- `core/runtime/persistence/factory.py:68-109` is a factory, not a process
  global singleton. The leaked object was the V5 persistence instance held by
  the reused global app.

## Positive root-cause classification

| Class | Result | Direct evidence |
| --- | --- | --- |
| A | YES, effective config leak | The real startup document was active during the failed V5 run and the V3 fixture did not override the config boundary. |
| B | YES | The resolver defaulted to `data/runtime-startup.json` when no isolated config was selected. |
| C | YES | `server.py` resolved and cached V5 globals at import. |
| D | YES | The old V3 fixture constructed `TestClient(server.app)` instead of an explicit Legacy app. |
| E | NO as a singleton | No RuntimePersistence singleton exists; the cached V5 instance was attached to the reused app. |
| F | YES | The old fix isolated the DB path but not mode/config/app state. |
| G | YES for the test boundary | The V3 fixture had no scoped environment cleanup/reset around the ambient V5 configuration. |
| H | YES | Global module/app state remained in the importing pytest process. |
| I | NO | No additional cause was required by the direct trace. |

This is why the correct repair is isolation, not re-enabling Legacy writes in
the V5 gateway.

## V3 contract

`tests/test_v3.py`, `tests/test_recovery_v3.py`, and
`tests/test_v3_function_matrix.py` are Legacy regression tests. Their contract
is now explicit:

```text
isolated Legacy DB
+ explicit Legacy runtime mode/config
+ fresh isolated server module and app
+ scoped persistence/StateStore lifecycle
+ no real 8787 network
```

They do not depend on whether real Production is currently Legacy or V5, and
they do not require V5 to expose retired V3 write routes.

## Old DB-decoupling fix versus current requirement

| Dimension | Old closure | Current requirement/result |
| --- | --- | --- |
| DB path | Explicit Legacy fixture and distinct V5/readonly paths | Complete; every V3 test owns a fresh DB path |
| Canonical path | `FRAMEFLOW_TEST_CANONICAL_DB` hook patched selected migration/runtime constants | Complete; V3 app construction does not use canonical Production |
| Runtime-startup path | Not isolated | Complete; fixture writes a unique temporary Legacy config |
| `FRAMEFLOW_RUNTIME_CONFIG` | Not scoped by V3 fixture | Complete; explicit fixture config wins and ambient values are restored |
| `runtime_mode` | DB was Legacy but mode could remain ambient V5 | Complete; module and app assert `legacy` |
| `server.app` | Reused process-global app | Complete; unique fresh `server.py` module/app per runtime |
| RuntimePersistence | No V3 reset of a V5 app-held instance | Complete; V5 app instances are distinct and disposed |
| StateStore factory | DB path isolation only | Complete through fresh V5 app construction and disposal |
| Module import cache | Global `server` import remained cached | Complete; unique module namespace is removed on teardown |
| Environment | Ambient Production values remained effective | Complete; runtime keys are scoped/restored |
| TestClient | Bound to global app | Complete; each fixture binds its own fresh app |
| Port/network | No V3-specific real-port guard | Complete; URL and socket guards fail on real 8787 |

## Repair

`tests/support/runtime_isolation.py` provides `create_legacy_test_app()` and
`create_v5_test_app()`. The helper writes a fixture-owned
`RuntimeStartupConfig`, scopes the runtime environment while importing a fresh
module, asserts DB/config/mode identity, and disposes persistence plus known
test files at teardown. `tests/conftest.py` adds an autouse guard for the
three Legacy regression files. No production source was changed.

Added regression coverage proves all of the following:

1. An ambient simulated V5 config cannot capture an explicit Legacy fixture.
2. A V5 retired V3 write route remains HTTP 501.
3. V5 → Legacy → V5 in one pytest process keeps the two route contracts and
   uses distinct app/persistence objects.
4. The exact post-cutover order can run V3 against an isolated Legacy app
   while an isolated V5 service is active, without changing V5 state.

## Verification record

```text
V3:                              37 passed
Schema/migration/runtime:       140 passed
Focused T03 core gates:          95 passed
Focused runtime-config checks:    3 passed
Post-cutover DB contract:         1 passed
Git safety:                      10 passed
Full tests directory:           281 passed
Isolation tests + V3:            40 passed
```

The exact isolated sequence used an ephemeral port (`28792`), not real
Production port 8787. It passed V5 readiness 19/19 and Legacy compatibility
17/17, then V3 37/37, then full 281/281. The simulated V5 health remained
`runtime_mode=v5`, `ready=true`; its logical fingerprint and config remained
unchanged.

## Preserved T03 evidence and real Production audit

The historical failed run remains unchanged:

```text
T03FINAL-20260829T002659Z-005e7ff9
```

Read-only preserved evidence confirms Candidate A/B, A0/B0 equivalence,
archive 5/5 readonly, maintenance freshness, and the terminal Candidate B
seal. Candidate B evidence remains sidecar-free, `journal_mode=DELETE`, four
stable samples, handles closed, rename passed, SEALED, reopened=false, and
post-seal DB open count 0. No Candidate B reopen was performed in this
closure.

Current real Production remains:

```text
canonical = D:\\11067\\CodexWorkspaces\\frameflow-v3\\data\\frameflow.db
schema = LEGACY_V3
tables = 41 (including sqlite_sequence)
schema version = 16
integrity_check = ok
foreign_key_check = 0
runtime-startup.json = absent
health = HTTP 200, runtime_mode=legacy, status=ready, ready=true
doctor.database = canonical path
```

The only real-port request in this closure was the explicitly read-only
independent health/doctor audit. V3 regression traffic to real 8787 was
blocked by the test guard and was zero. No maintenance operation, Task
mutation, canonical replacement, migration, or Production V5 startup config
was performed.

## Final status

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
READY FOR NEW FINAL PRODUCTION CUTOVER AUTHORIZATION = YES
```
