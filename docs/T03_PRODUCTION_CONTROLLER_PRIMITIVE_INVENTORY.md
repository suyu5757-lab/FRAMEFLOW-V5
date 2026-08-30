# T03 Production Controller primitive inventory

This inventory is the design boundary for the formal live controller.  The
controller must delegate to these implementations and may not reproduce their
SQLite, port, task, migration, or swap semantics.

| Step | Authoritative primitive | Production mutation | Tests |
| --- | --- | ---: | --- |
| ADMIN / formal Python | `core/migration/production_environment.py:88` `verify_production_interpreter` | No | `tests/runtime/test_production_environment.py` |
| Port ownership / P4 | `core/migration/port_ownership.py:152` `inspect_port_owner`; `:189` `build_exclusive_port_evidence` | No | `tests/runtime/test_production_port_ownership.py` |
| Maintenance enter/start/restore | `scripts/frameflow-maintenance.ps1:1-470` | Yes | `tests/runtime/test_production_port_ownership.py`, `tests/migration/test_t03_final_preswap_gates.py` |
| Legacy checkpoint / fingerprint | `core/migration/cutover.py:159` `checkpoint_database`; `:415` `fingerprint_database` | No | `tests/migration/test_runtime_startup_cutover.py` |
| SQLite-consistent snapshot | `core/migration/backup.py:117` `create_backup` | Candidate/archive only | migration tests |
| Candidate migration | `core/migration/v3_to_v5.py:694` `migrate_v3_to_v5` | Candidate only | `tests/migration/test_t02_runtime_migration.py` |
| Candidate A evidence | `core/migration/equivalence.py` `build_candidate_evidence`, `build_candidate_a_lifecycle_evidence` | Candidate only | `tests/migration/test_candidate_equivalence.py` |
| Candidate A runtime probe | `scripts/verify_t03_sol_final.py:274` `run_http_gate` and formal launcher | Candidate only | `tests/runtime/test_production_environment.py` |
| Candidate B finalization | `core/migration/cutover.py:238` `stabilize_candidate_b_database` | Candidate only | `tests/migration/test_candidate_b_terminal_seal.py` |
| Candidate B seal | `core/migration/candidate_b_lifecycle.py:52` `CandidateBTerminalSeal` | Candidate only | `tests/migration/test_candidate_b_terminal_seal.py` |
| Archive / config / freshness | `core/migration/preswap.py:112-352` | Archive/config only | `tests/migration/test_t03_final_preswap_gates.py` |
| A0/B0 aggregate | `core/migration/equivalence.py` `verify_final_candidate_gate` | No | `tests/migration/test_candidate_equivalence.py` |
| Atomic V5 replacement | `core/migration/cutover.py:602` `perform_production_cutover` | **Yes** | cutover and port-ownership tests |
| V5 runtime start / restart | `scripts/frameflow-maintenance.ps1:428` `StartTarget`; installed task | **Yes** | launcher/runtime tests |
| Actual runtime SQLite contract | `scripts/verify_t03_sol_final.py:245` `live_runtime_sqlite_contract`; V5 endpoint | No | `tests/runtime/test_server_v5_persistence.py` |
| Workbench / Legacy compatibility | `scripts/verify_t03_sol_final.py:274` `run_http_gate` | Fixture writes only | readiness/launcher tests |
| Rollback snapshot | `core/migration/cutover.py:502` `create_rollback_snapshot`; `backup.py:164` `restore_backup` | **Yes** | cutover tests |

The live controller owns only: run identity, state transitions, aggregate gate
evidence, strict counters, callback ordering, and fail-closed rollback routing.
