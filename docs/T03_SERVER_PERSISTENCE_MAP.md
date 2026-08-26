# FRAMEFLOW V5.3.2 — T03-R2 Server Persistence Map

Audit date: 2026-08-26
Default mode: `legacy`
Isolated mode: `FRAMEFLOW_RUNTIME_MODE=v5` with explicit `FRAMEFLOW_V5_DB`

## Counting rule

The static server contains 144 decorated handlers that use the legacy
`Database` helper, plus non-route helper call sites. Those handlers remain for
the default legacy mode and are not counted as V5 runtime calls. In explicit
V5 mode, `v5_runtime_gateway` intercepts every `/api/v2/` request except the
non-persistent workflow manifest route; the 17 calls below are the complete
V5-mode persistence surface. An unsupported V3 handler is never invoked and
returns a clear 501 response.

## V5-mode call matrix

| Caller | Function / endpoint | Current DB method | Tables used | Read/Write | V5 target | Status |
|---|---|---|---|---|---|---|
| `server.py` lifespan | V5 startup | `create_runtime_persistence()` | all 11 detected; StateStore PRAGMAs | R/W connection setup | StateStore factory | PASS |
| `server.py` | `GET /api/health` | `health_payload()` | PRAGMA only | Read | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/settings` | `settings_payload()` | none; provider persistence deferred | Read projection | Typed facade | V5_NATIVE |
| `server.py` | `GET /api/v2/system/data-audit` | `data_audit()` | projects, sequences, shots, assets, artifacts, generations, reviews | Read | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/dashboard` | `dashboard_payload()` | projects, shots, events | Read | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects` | `list_projects_envelope()` | projects, events, shots, assets, artifacts | Read | StateStore | V5_NATIVE |
| `server.py` | `POST /api/v2/projects` | `create_project()` | projects, sequences, events | Write | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}` | `project_envelope()` | projects, shots, assets, artifacts, events | Read | StateStore | V5_NATIVE |
| `server.py` | `PATCH /api/v2/projects/{id}` | `update_project_metadata()` | projects, events | Write | StateStore transaction | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/graph` | `graph_envelope()` | projects | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/timeline` | `timeline_envelope()` | projects | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/timeline/preflight` | `timeline_preflight()` | projects, shots | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/story` | `story_envelope()` | projects, shots | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/story/runs` | `story_runs()` | projects only; returns no T05 lifecycle | Read | StateStore | V5_NATIVE / T05 empty projection |
| `server.py` | `GET /api/v2/projects/{id}/assets` | `asset_library()` | assets, artifacts | Read | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/asset-board` | `asset_board()` | projects, shots, assets | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/asset-audit` | `asset_audit()` | assets, artifacts | Read projection | StateStore | V5_NATIVE |
| `server.py` | `GET /api/v2/projects/{id}/audio-studio` | `audio_studio()` | projects only; empty execution projection | Read | StateStore | V5_NATIVE / future audio execution |
| `server.py` | `GET /api/v2/legacy/shots/{id}` | `legacy_shot()` | protected V3 snapshot | Read only | `LegacyReadOnlyCompatibility` | LEGACY_READ_ONLY |

The table has 19 rows because the startup boundary is included for ownership
evidence; the endpoint call count is 18, of which 17 are V5-native and one is
legacy-read-only compatibility.

## V3 and future call paths

The legacy `server.py` handlers still contain direct V3 SQL for provider
profiles, graph/timeline storage, workflow runs, task lifecycle, asset QA,
recovery, and media operations. They remain available only when the default
runtime mode is `legacy`. In V5 mode, the gateway prevents dispatch to them;
they cannot open the candidate or the legacy snapshot.

| Surface | Classification in V5 mode | Behavior |
|---|---|---|
| Queue/claim/retry/cancel/heartbeat/worker lifecycle | `FUTURE_T05` | Not implemented; request is rejected with 501. |
| Provider submission/generation execution | `FUTURE_T05` | Not implemented; no provider tables or writes are introduced. |
| V3 graph/timeline/workflow persistence beyond P0 projections | `INVALID_DIRECT_ACCESS` if bypassed | Gateway blocks it with 501; no direct DB call is reachable. |
| V3 recovery/backup/asset QA writes | `INVALID_DIRECT_ACCESS` if bypassed | Gateway blocks it with 501; default legacy mode is unchanged. |

## Frontend critical API set

The actual `web/src/api.ts` client calls these paths during initial load and
project snapshot loading:

- initial: `/api/v2/projects`, `/api/v2/dashboard`, `/api/v2/settings`, and
  `/api/v2/workflows`;
- project snapshot: project graph, timeline, timeline preflight, story, story
  runs, assets, asset-board, dashboard, asset-audit, and audio-studio;
- P0 validation also checks `/api/health`, `/api/v2/system/data-audit`, and
  the retired `/api/projects` path.

All of these were exercised by the isolated V5 backend test. The workflow
manifest route remains a static application response and does not open a DB.
