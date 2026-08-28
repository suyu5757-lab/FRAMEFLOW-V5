# FRAMEFLOW V5.3.2 — T03 V5 Production Readiness Predicate Matrix

Date: 2026-08-28
Failed production run: `T03FINAL-20260828T110620Z-817060f4`

## Exact code path

```text
GET /api/health
  -> server.v3_only_gateway
  -> server._v5_runtime_response
  -> RuntimePersistence.health_payload
  -> LegacyReadOnlyCompatibility.provider_readiness_inputs
  -> readiness.evaluate_capabilities
  -> readiness.readiness_summary
  -> status / ready
```

The V5 gateway intercepts `/api/health` at `server.py:330`; the normal Legacy
handler at `server.py:538` uses the same shared evaluator. The application
readiness standard remains:

```text
ready = orchestrator_capability_ready AND media_capability_available
media_capability_available = any(image, video, tts, music, sfx)
```

## Predicate matrix

| Predicate | Code location | Candidate A | Failed Production V5 | Required | Difference |
| --- | --- | ---: | ---: | ---: | --- |
| Bound capability provider is enabled, last probe is `ok=true`, and bound model is available | `core/runtime/readiness.py:43-79`, fed by `core/migration/legacy_compat.py:132` | Pre-fix `false` / closure `true` for orchestrator and video | `false` for every capability because V5 returned synthetic `unbound` entries | Supporting predicate for each capability used below | `RuntimePersistence.health_payload()` previously never read the Legacy archive provider state |
| `orchestrator_capability_ready` | `core/runtime/readiness.py:97-101` | Pre-fix `false` / closure `true` | `false` | `true` | Valid archived `opencode-default` binding and probe were discarded by the old V5 placeholder |
| `media_capability_available` | `core/runtime/readiness.py:103-112` | Pre-fix `false` / closure `true` via `video` | `false` | `true` | Valid archived `jimeng-default` video binding and probe were discarded by the old V5 placeholder |
| Application `ready` (`orchestrator AND media`) | `core/runtime/readiness.py:84-119` | Pre-fix `false` / closure `true` | `false` | `true` | The old Candidate A smoke gate checked HTTP/mode and API counts, but not `health.ready=true` |

## Evidence

The saved Candidate A formal evidence and the failed production evidence both
showed `HTTP 200`, `runtime_mode=v5`, `status=not_ready`, and `ready=false`.
Candidate A nevertheless reported 19/19 and 17/17 because its old formal gate
did not require `ready=true`. The copied isolated reproduction at
`data/.cutover/T03READINESS-20260828T112842Z-161ea33c` reproduced the same
failure before the repair.

After repair, the production-like certification at
`data/.cutover/T03READINESS-CERT-20260828T114614Z-23c7a59a` reported:

```text
production = true
isolated simulation database = v5-certification.db
first health = ready=true, runtime_mode=v5
restart health = ready=true, runtime_mode=v5
first/restart Workbench = 19/19
first/restart SH004-SH020 = 17/17
WAL = wal
foreign_keys = 1
busy_timeout = 5000
integrity_check = ok
foreign_key_check = 0
```

No readiness predicate was weakened. The V5 archive projection is read-only;
provider state is not written into the V5 database.
