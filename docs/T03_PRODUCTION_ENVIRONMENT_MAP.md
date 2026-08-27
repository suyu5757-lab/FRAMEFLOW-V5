# FRAMEFLOW V5.3.2 Production Environment Map

Audit date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before repair: `e213121feb9ed76bc23433fd85e064445b1938d9`

## Interpreter map

| Context | Interpreter | `sys.prefix` | `sys.base_prefix` | Python | Deterministic source |
|---|---|---|---|---|---|
| Production scheduled task | `D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe` | `D:\11067\CodexWorkspaces\frameflow-v3\.venv` | `C:\Users\11067\AppData\Local\Programs\Python\Python314` | 3.14.6 | `FRAMEFLOW-V3-Service` action |
| Project `.venv` | `D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe` | `D:\11067\CodexWorkspaces\frameflow-v3\.venv` | `C:\Users\11067\AppData\Local\Programs\Python\Python314` | 3.14.6 | project-local absolute path |
| Pytest before repair | `C:\Users\11067\AppData\Local\Programs\Python\Python314\python.exe` | global Python 3.14 root | same as prefix | 3.14.6 | Codex invoked `python -m pytest` |
| Codex shell `python` | `C:\Users\11067\AppData\Local\Programs\Python\Python314\python.exe` | global Python 3.14 root | same as prefix | 3.14.6 | user PATH resolution |
| Candidate smoke before repair | global Python above | global Python 3.14 root | same as prefix | 3.14.6 | harness used its invoking `sys.executable` |
| Formal launcher probe after repair | project `.venv` above | project `.venv` | global Python 3.14 root | 3.14.6 | probe refuses every other interpreter |
| Migration/operator commands in this audit | global Python above | global Python 3.14 root | same as prefix | 3.14.6 | Codex shell invocation; never the production server proof |

## Formal launcher chain

The installed `FRAMEFLOW-V3-Service` scheduled task is deterministic:

```text
wscript.exe scripts/run-hidden.vbs
  -> D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
  -> -m uvicorn server:app --host 127.0.0.1 --port 8787
  -> working directory D:\11067\CodexWorkspaces\frameflow-v3
```

It does not resolve `python` through PATH. After dependency synchronization,
this exact task replaced the temporary global-Python Legacy process and returned
HTTP 200, version 3.0.0, schema 16, `runtime_mode=legacy`.

## Why 109 tests missed the production failure

The 109-test suite was launched with the global Python interpreter. That
environment contained `jsonschema 4.26.0`, SQLAlchemy, and Alembic, so imports,
migration tests, StateStore tests, and candidate backend smoke all passed.

Production used the project `.venv`. Before this repair, that environment lacked
both the newly required `jsonschema` package and already-declared SQLAlchemy and
Alembic. `pip check` still returned success because it checks dependency
relationships among installed distributions; it does not compare installed
top-level packages with `requirements.txt`. The scheduled task therefore failed
while importing `core.migration.legacy_compat`, before FastAPI lifespan startup.

## Dependency state

The repository uses `requirements.txt`; no `pyproject.toml`, lock file,
constraints file, Pipfile, Poetry file, or setup metadata was present.

Before repair:

```text
global Python: jsonschema 4.26.0 present
formal .venv: jsonschema absent
formal .venv: SQLAlchemy and Alembic absent despite existing declarations
```

After repair:

```text
requirements.txt: jsonschema==4.26.0
formal .venv: jsonschema 4.26.0
formal .venv: requirements synchronized without upgrading satisfied packages
formal .venv pip check: No broken requirements found.
```

There is no complete lock for all runtime packages. Exact `jsonschema` pinning
and the new interpreter/import/pip/formal-launcher gates close the observed
production risk; full transitive reproducibility remains a documented future
dependency-management risk rather than a reason to redesign packaging in T03.
