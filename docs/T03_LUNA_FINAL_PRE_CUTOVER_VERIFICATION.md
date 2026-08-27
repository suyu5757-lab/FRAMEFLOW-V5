# FRAMEFLOW V5.3.2 — Luna Final Pre-Cutover Verification

Date: 2026-08-27
Branch: `dev/v5.3.2`
HEAD before this verification commit: `8612bd05b394b0d8ecc3a12ee482a521e92628d6`

## Final verdict

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
READY FOR FINAL PRODUCTION CUTOVER = YES
```

The final production cutover stop rule was honored. No production database
replacement, runtime source-of-truth switch, archive replacement, or V5
production startup was performed.

## Environment and dependency gate

```text
Formal interpreter = D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
Python = 3.14.6
sys.prefix = D:\11067\CodexWorkspaces\frameflow-v3\.venv
jsonschema = 4.26.0
SQLAlchemy = 2.0.52
Alembic = import OK
pip check = No broken requirements found.
requirements dry-run consistency = PASS
runtime imports = PASS
```

`pytest` was installed into the same project `.venv` because it was absent from
the existing test environment. Runtime dependency declarations remain in
`requirements.txt`; no global interpreter was used.

## Gate repair

The old gate required both `Candidate B backend-opened = NO` and formal
launcher evidence naming Candidate B. Those conditions were contradictory.

The implemented model is now:

```text
Candidate A = SMOKE / APPLICATION-ENVIRONMENT EVIDENCE
Candidate B = SWAP / CLOSED-DATABASE EVIDENCE
```

Candidate A owns the formal launcher and restart evidence. Candidate B is
validated through closed-file SQLite inspection, deterministic schema/data
fingerprints, row accounting, and a real rename probe. Candidate B remains a
hard `backend-opened = NO` gate.

The gate records and compares:

```text
source_legacy_sha
migration revision
migration implementation version
schema contract version
schema fingerprint
logical domain-data fingerprint
business primary keys
row accounting
```

The logical fingerprint uses canonical row serialization ordered by primary
key across all 11 V5 domain tables. It does not compare SQLite file SHA as a
data-equivalence substitute.

## Final test run

Final clean A/B evidence run:

```text
Run root = D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\LUNA-DIAG-20260827T203919-490f4644
Frozen source SHA = 0fc5d85d3da9848ace81dd4bd3ce79625752d347e9dd6aa0915b6b4f1710b2b3
Candidate model = A_SMOKE + B_SWAP
```

Candidate A:

```text
path = D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\LUNA-DIAG-20260827T203919-490f4644\candidate-a\v5-candidate.db
formal launcher evidence = ...\candidate-a\formal-launcher-evidence.json
source SHA = 0fc5d85d3da9848ace81dd4bd3ce79625752d347e9dd6aa0915b6b4f1710b2b3
schema SHA = afaf402223dc29d9b33e9e3ad7fadc52aed94f7d907e8fb6e1f779e1f4b637db
logical SHA = 9830759c4790dbd4833c7dd5e0636f3a3bc4ad4ca0f4b24e09c6b81ddd26f980
domain tables = 11
formal launcher = PASS
health = PASS, runtime_mode=v5
Workbench first start = 19/19
SH004-SH020 first start = 17/17
restart = PASS
Workbench after restart = 19/19
SH004-SH020 after restart = 17/17
rename = PASS
backend-opened = YES (permitted for Candidate A)
```

Candidate B:

```text
path = D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\LUNA-DIAG-20260827T203919-490f4644\candidate-b\v5-candidate.db
source SHA = 0fc5d85d3da9848ace81dd4bd3ce79625752d347e9dd6aa0915b6b4f1710b2b3
schema SHA = afaf402223dc29d9b33e9e3ad7fadc52aed94f7d907e8fb6e1f779e1f4b637db
logical SHA = 9830759c4790dbd4833c7dd5e0636f3a3bc4ad4ca0f4b24e09c6b81ddd26f980
domain tables = 11
schema drift = 0
integrity = PASS
foreign_key_check = 0
journal_mode = WAL
foreign_keys = ON
busy_timeout = 5000
validation = PASS
backend-opened = NO
rename = PASS
```

Candidate B was only inspected through short-lived raw SQLite validation and
fingerprint connections before the rename probe. After the successful rename
probe, Candidate B was not opened again.

A/B equivalence:

```text
same frozen source = PASS
migration revision = 20260826_01 on both
migration implementation = v3_to_v5:20260826_01 on both
schema contract = runtime-mvp:5.3.2 on both
schema equivalence = PASS
logical data equivalence = PASS
business PK equivalence = PASS
row accounting equivalence = PASS
UNKNOWN = 0
UNACCOUNTED = 0
SH004-SH020 accounted = 17/17
```

The migration manifest contains 17 `migration_unmapped_rows`; these are the
known legacy-only shots preserved through the explicit
`LEGACY_READ_ONLY_COMPAT` classification. They are not final `UNACCOUNTED`
records; the required-shot accounting is 17/17 and final `UNACCOUNTED=0`.

## Test results

All commands used the formal project interpreter:

```text
tests/runtime/test_production_environment.py = 10 passed
tests/migration/test_runtime_startup_cutover.py = 2 passed
tests/runtime/test_t03_r3c_handles.py + test_t03_r3d_handles.py = 10 passed
tests/runtime/test_server_v5_persistence.py = 6 passed
tests/migration/test_t03_r3b_cutover.py = 3 passed
tests/migration/test_candidate_equivalence.py = 9 passed
tests/schema tests/migration tests/runtime = 91 passed
tests/test_v3.py tests/test_recovery_v3.py tests/test_v3_function_matrix.py = 37 passed
```

```text
Existing pre-existing schema/migration/runtime tests = 82 passed
New Candidate equivalence tests = 9 passed
V3 regression = PASS (37 passed)
Total unique relevant tests = 128 passed
Failed = 0
Blocked = 0
```

The only warning was the existing Starlette/httpx deprecation warning.

## Production safety audit

```text
Production DB = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
current production SHA = 38c4342bae668e5d6198602059c83bb261b6206a7de04e17e20cf11838ca30d8
schema = LEGACY_V3
tables = 41
integrity_check = ok
foreign_key_violations = 0
runtime-startup.json present = NO
8787 listener = NONE
```

The production file SHA differs from the frozen backup file SHA because the
SQLite consistent backup creates an independent database file layout. A
read-only comparison found identical table sets, row counts, physical stats,
and logical rows between the current production file and the frozen snapshot.

```text
Production DB replaced = NO
Production DB intentionally modified by this run = NO
Production DB staged = NO
Candidate DB staged = NO
Dual write = NO
Dual source of truth = NO
Independent final review = PASS
```

## Files changed in this run

```text
core/migration/cutover.py
core/migration/equivalence.py
pytest.ini
scripts/verify_t03_sol_final.py
tests/migration/test_candidate_equivalence.py
docs/T03_LUNA_FINAL_PRE_CUTOVER_VERIFICATION.md
```

Only these files are intended for the verification commit. Existing dirty and
untracked user files were preserved and were not staged.

```text
Commit = this report's containing verification commit
```

The final production cutover remains a separate, explicitly authorized step.
