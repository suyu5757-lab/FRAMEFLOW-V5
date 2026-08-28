# T03 full-regression DB assumption matrix

## Reproduction record

The original post-swap command was:

```powershell
& $PY -m pytest tests/schema tests/migration tests/runtime -q
```

It was reproduced without touching production in an isolated workspace whose
canonical database was migrated to V5 and whose Legacy source was a separate
read-only SQLite file. The historical result was **8 failures and 23 errors**.
Five additional failures seen in an early cloned reproduction were discarded
as clone-only interpreter/root-path noise; they were not present in the real
post-swap result. The 31 rows below are the exact production-relevant
inventory.

| Test | File | Failure | DB path used | Expected schema | Actual assumption | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| `test_authorized_cutover_persists_explicit_restart_safe_v5_configuration` | `tests/migration/test_runtime_startup_cutover.py` | migration source rejected | canonical | Legacy V3 | canonical is migration input | HARDCODED_CANONICAL_PATH |
| `test_failed_replacement_restores_the_prior_runtime_configuration` | same | migration source rejected | canonical | Legacy V3 | canonical is migration input | HARDCODED_CANONICAL_PATH |
| `test_production_backup_is_read_only_and_hash_unchanged` | `tests/migration/test_t02_runtime_migration.py` | backup saw V5 table set | canonical | Legacy V3 | canonical is a Legacy backup fixture | LEGACY_ARCHIVE_ALIAS |
| `test_h3_runtime_persistence_dispose_then_real_rename_probe` | `tests/runtime/test_t03_r3c_handles.py` | Legacy adapter rejected V5 | canonical | Legacy V3 | V5 test supplied canonical as Legacy | IMPLICIT_LEGACY_FIXTURE |
| `test_persistence_factory_shutdown_is_idempotent_and_releases_pool` | `tests/runtime/test_t03_r3d_handles.py` | Legacy adapter rejected V5 | canonical | Legacy V3 | V5 test supplied canonical as Legacy | IMPLICIT_LEGACY_FIXTURE |
| `test_all_required_legacy_shots_are_accounted_before_cutover` | `tests/runtime/test_t03_runtime_ownership.py` | SH accounting rejected V5 | canonical | Legacy V3 | canonical is historical-shot source | HARDCODED_CANONICAL_PATH |
| `test_fresh_candidate_is_verified_without_touching_production` | same | migration rejected V5 source | canonical | Legacy V3 | canonical is migration fixture | HARDCODED_CANONICAL_PATH |
| `test_legacy_compatibility_is_read_only` | same | Legacy adapter rejected V5 | canonical | Legacy V3 | canonical is readonly archive | LEGACY_ARCHIVE_ALIAS |
| `test_e4_formal_launcher_candidate_startup` | `tests/runtime/test_production_environment.py` | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | HARDCODED_CANONICAL_PATH |
| `test_e5_formal_launcher_first_start_19_of_19` | same | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | HARDCODED_CANONICAL_PATH |
| `test_e6_formal_launcher_first_start_17_of_17` | same | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | HARDCODED_CANONICAL_PATH |
| `test_e7_formal_launcher_restart_gates` | same | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | HARDCODED_CANONICAL_PATH |
| `test_e8_wrong_interpreter_fails_identity_gate` | same | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | HARDCODED_CANONICAL_PATH |
| `test_e10_pre_swap_failure_leaves_production_untouched` | same | fixture setup failed | canonical | Legacy V3 | canonical copied as Legacy | PRODUCTION_DB_SIDE_EFFECT |
| `test_default_legacy_mode_still_starts_in_an_isolated_database` | `tests/runtime/test_server_v5_persistence.py` | class setup failed | canonical | Legacy V3 | canonical feeds V5 test migration | IMPLICIT_LEGACY_FIXTURE |
| `test_facade_transaction_rolls_back_a_failed_project_update` | same | class setup failed | canonical | Legacy V3 | canonical feeds V5 test migration | IMPLICIT_LEGACY_FIXTURE |
| `test_legacy_select_and_all_sql_writes_are_blocked` | same | class setup failed | canonical | Legacy V3 | canonical feeds V5 test migration | LEGACY_ARCHIVE_ALIAS |
| `test_v5_backend_p0_routes_and_legacy_bridge` | same | class setup failed | canonical | Legacy V3 | canonical feeds V5 test migration | IMPLICIT_LEGACY_FIXTURE |
| `test_v5_mode_requires_an_explicit_non_production_candidate` | same | class setup failed | canonical | Legacy V3 | canonical feeds V5 test migration | RUNTIME_MODE_ASSUMPTION |
| `test_v5_project_metadata_write_reopens_and_production_is_unchanged` | same | class setup failed | canonical | Legacy V3 | canonical is both source and immutable control | PRODUCTION_DB_SIDE_EFFECT |
| `test_valid_persisted_configuration_is_authoritative_and_opens` | `tests/runtime/test_v5_startup_config.py` | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_v5_missing_legacy_configuration_fails_closed` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_backend_process_exits_during_startup_when_v5_config_is_incomplete` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_backend_startup_rejects_invalid_legacy_sources[invalid-path]` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_backend_startup_rejects_invalid_legacy_sources[same-as-v5]` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_backend_startup_rejects_invalid_legacy_sources[random-sqlite]` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_v5_invalid_legacy_path_fails_closed` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_v5_database_cannot_be_its_own_legacy_source` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | RUNTIME_MODE_ASSUMPTION |
| `test_random_sqlite_database_is_rejected_as_legacy` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |
| `test_legacy_archive_allows_select_and_blocks_sql_writes` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | LEGACY_ARCHIVE_ALIAS |
| `test_persisted_config_has_complete_audit_metadata` | same | module fixture failed | canonical | Legacy V3 | canonical feeds migration | IMPLICIT_LEGACY_FIXTURE |

## Resolution

All fixture-dependent tests now create `legacy_v3.db` below
`FRAMEFLOW_TEST_TMP`, then create an independent V5 candidate and a separate
Legacy readonly source. The only remaining `PRODUCTION_DATABASE` references
are three negative safety-guard assertions in
`test_t02_runtime_migration.py`; they do not open, inspect, or assume the
schema of the production path.

Classification totals: HARDCODED_CANONICAL_PATH=9,
IMPLICIT_LEGACY_FIXTURE=14, GLOBAL_DB_SINGLETON=0,
PRODUCTION_DB_SIDE_EFFECT=2, LEGACY_ARCHIVE_ALIAS=4,
TEST_ENVIRONMENT_LEAK=0, RUNTIME_MODE_ASSUMPTION=2, OTHER=0.
