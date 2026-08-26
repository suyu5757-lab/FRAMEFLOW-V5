# FRAMEFLOW V5.3.2

## T02-R V3 -> V5 Data Map

This is a side-by-side migration map, not a production cutover record. All source reads use SQLite read-only URI. All V5 writes go only to temporary backup/candidate databases. The production data/frameflow.db was never passed as an Alembic candidate.

## 1. Source DB Reality

| Field | Captured fact |
|---|---|
| Source | D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db |
| Schema | V3 legacy schema_migrations version 16 |
| Tables | 41 SQLite tables, including sqlite_sequence |
| PRAGMA integrity_check | ok |
| PRAGMA journal_mode | wal |
| PRAGMA foreign_keys | 0 on the read-only probe connection; V3 Database.connect() enables it per application connection |
| PRAGMA busy_timeout | 5000 |
| Source write policy | READ_ONLY for this task |

The complete source schema was captured by inspect_legacy_database(). Each row below lists columns, SQLite type, NN (not null), PK, real foreign keys, and index names. Index suffix U means unique.

## 2. Complete 41-table Inventory

| Table | Rows | Classification | Columns (type/constraints) | Foreign keys | Indexes |
|---|---:|---|---|---|---|
| agent_candidate_versions_v5 | 0 | EMPTY | id TEXT PK; plan_id TEXT NN; project_id TEXT NN; kind TEXT NN; target_id TEXT; version INTEGER NN; status TEXT NN; content_json TEXT NN; metadata_json TEXT NN; created_at TEXT NN; accepted_at TEXT | project_id -> projects.id; plan_id -> agent_plans_v5.id | idx_agent_candidates_project; sqlite_autoindex_agent_candidate_versions_v5_1 U |
| agent_plan_events_v5 | 0 | EMPTY | id INTEGER PK; plan_id TEXT NN; event_type TEXT NN; detail_json TEXT NN; created_at TEXT NN | plan_id -> agent_plans_v5.id | idx_agent_plan_events_plan |
| agent_plans_v5 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; status TEXT NN; message TEXT NN; skill_id TEXT; skill_version TEXT; provider_profile_id TEXT; provider_model TEXT; base_project_revision INTEGER NN; base_graph_revision INTEGER NN; input_snapshot_json TEXT NN; patch_json TEXT NN; preview_json TEXT NN; decision_json TEXT NN; error_json TEXT; created_at TEXT NN; updated_at TEXT NN | project_id -> projects.id | idx_agent_plans_project; sqlite_autoindex_agent_plans_v5_1 U |
| approval_gates_v3 | 0 | EMPTY | id TEXT PK; run_id TEXT NN; node_id TEXT; reason TEXT NN; status TEXT NN; estimate_json TEXT NN; decision_detail_json TEXT NN; decided_at TEXT; created_at TEXT NN; approval_consumed_at TEXT | run_id -> workflow_runs_v3.id | sqlite_autoindex_approval_gates_v3_1 U |
| approvals | 29 | ARCHIVE_ONLY | id TEXT PK; project_id TEXT; subject_type TEXT NN; subject_id TEXT NN; decision TEXT NN; detail_json TEXT NN; created_at TEXT NN | none | sqlite_autoindex_approvals_1 U |
| artifact_lineage_v3 | 0 | EMPTY | id INTEGER PK; project_id TEXT NN; parent_artifact_id TEXT NN; child_artifact_id TEXT NN; relation TEXT NN; node_id TEXT; created_at TEXT NN | child_artifact_id -> artifacts.id; parent_artifact_id -> artifacts.id; project_id -> projects.id | idx_lineage_v3_child; idx_lineage_v3_parent; sqlite_autoindex_artifact_lineage_v3_1 U |
| artifacts | 31 | MIGRATE | id TEXT PK; project_id TEXT; artifact_type TEXT NN; role TEXT; version INTEGER NN; local_path TEXT NN; sha256 TEXT NN; mime_type TEXT; metadata_json TEXT NN; provider_profile_id TEXT; provider_model TEXT; prompt_version TEXT; task_id TEXT; qa_owner TEXT; qa_decision TEXT NN; status TEXT NN; created_at TEXT NN; logical_asset_id TEXT; asset_class TEXT; asset_role TEXT; collection TEXT NN; intake_status TEXT NN; source_type TEXT; generation_id TEXT; attempt_number INTEGER NN; qa_report_json TEXT NN; rejection_reason TEXT; supersedes_artifact_id TEXT; updated_at TEXT | project_id -> projects.id | idx_artifacts_project_created_v14; idx_artifacts_project_logical_created_v13; sqlite_autoindex_artifacts_1 U |
| asset_boards_v7 | 1 | ARCHIVE_ONLY | project_id TEXT PK; revision INTEGER NN; board_json TEXT NN; created_at TEXT NN; updated_at TEXT NN | project_id -> projects.id | idx_asset_boards_updated; sqlite_autoindex_asset_boards_v7_1 U |
| asset_comparisons_v4 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT NN; comparison_group TEXT NN; strategy TEXT NN; prompt_version TEXT; candidates_json TEXT NN; notes TEXT NN; created_at TEXT NN; updated_at TEXT NN | none | idx_asset_comparisons_project_logical_created_v13; idx_asset_comparisons_v4_asset; sqlite_autoindex_asset_comparisons_v4_1 U |
| asset_dependencies_v4 | 38 | ARCHIVE_ONLY | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT NN; dependency_asset_id TEXT NN; shot_id TEXT; relation TEXT NN; role TEXT; required INTEGER NN; created_at TEXT NN | none | idx_asset_dependencies_project_logical_created_v13; idx_asset_deps_v4_asset; sqlite_autoindex_asset_dependencies_v4_1 U; sqlite_autoindex_asset_dependencies_v4_2 U |
| asset_events | 141 | DERIVE | id INTEGER PK; project_id TEXT; artifact_id TEXT; logical_asset_id TEXT; from_status TEXT; to_status TEXT NN; detail_json TEXT NN; created_at TEXT NN | none | none |
| asset_qa_runs | 29 | ARCHIVE_ONLY | id TEXT PK; project_id TEXT NN; artifact_id TEXT NN; logical_asset_id TEXT NN; qa_owner TEXT NN; qa_type TEXT NN; status TEXT NN; decision TEXT; report_json TEXT NN; provider_profile_id TEXT; provider_model TEXT; capability TEXT; blocked_reason TEXT; started_at TEXT; finished_at TEXT; created_at TEXT NN | artifact_id -> artifacts.id; project_id -> projects.id | sqlite_autoindex_asset_qa_runs_1 U |
| asset_reference_roles_v4 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT NN; reference_id TEXT NN; reference_kind TEXT NN; artifact_id TEXT; role TEXT NN; source TEXT NN; notes TEXT NN; created_at TEXT NN; updated_at TEXT NN; priority INTEGER NN; scope TEXT NN; authority TEXT NN; conflict_group TEXT; effective_version TEXT | effective_version -> asset_versions.id; artifact_id -> artifacts.id; project_id -> projects.id | idx_asset_refs_v12_authority; idx_asset_refs_v4_asset; sqlite_autoindex_asset_reference_roles_v4_1 U; sqlite_autoindex_asset_reference_roles_v4_2 U |
| asset_versions | 29 | MIGRATE | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT NN; asset_class TEXT NN; version INTEGER NN; artifact_id TEXT NN; prompt_version TEXT; prompt_version_id TEXT; status TEXT NN; is_active INTEGER NN; registration_json TEXT NN; created_at TEXT NN; approved_at TEXT | prompt_version_id -> prompt_versions.id; artifact_id -> artifacts.id; project_id -> projects.id | idx_asset_versions_project_version_v14; idx_asset_versions_project_logical_version_v13; sqlite_autoindex_asset_versions_1 U; sqlite_autoindex_asset_versions_2 U |
| audit_events_v16 | 17 | DERIVE | id TEXT PK; project_id TEXT; actor TEXT NN; action TEXT NN; target_type TEXT NN; target_id TEXT NN; reason TEXT NN; before_json TEXT NN; after_json TEXT NN; result TEXT NN; metadata_json TEXT NN; created_at TEXT NN | none | idx_audit_events_v16_target_created; idx_audit_events_v16_project_created; sqlite_autoindex_audit_events_v16_1 U |
| backup_records_v11 | 13 | ARCHIVE_ONLY | id TEXT PK; database_path TEXT NN; database_sha256 TEXT NN; manifest_path TEXT NN; manifest_sha256 TEXT NN; project_id TEXT; status TEXT NN; detail_json TEXT NN; created_at TEXT NN; verified_at TEXT | none | sqlite_autoindex_backup_records_v11_1 U |
| capability_bindings | 2 | ARCHIVE_ONLY | capability TEXT PK; provider_profile_id TEXT NN; model TEXT; updated_at TEXT NN | provider_profile_id -> provider_profiles.id | sqlite_autoindex_capability_bindings_1 U |
| conversations | 0 | EMPTY | id TEXT PK; project_id TEXT; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_conversations_1 U |
| generation_snapshots_v9 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT; artifact_id TEXT; operation_type TEXT NN; status TEXT NN; prompt_version_id TEXT NN; prompt_sha256 TEXT NN; prompt_body TEXT NN; reference_snapshot_json TEXT NN; provider_profile_id TEXT; provider_model TEXT; parameters_json TEXT NN; error_json TEXT; created_at TEXT NN; updated_at TEXT NN | artifact_id -> artifacts.id; prompt_version_id -> prompt_versions.id; project_id -> projects.id | idx_generation_snapshots_v9_prompt; idx_generation_snapshots_v9_asset; sqlite_autoindex_generation_snapshots_v9_1 U |
| media_proxies_v6 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; artifact_id TEXT NN; source_sha256 TEXT NN; preset TEXT NN; status TEXT NN; local_path TEXT; metadata_json TEXT NN; error_json TEXT; created_at TEXT NN; updated_at TEXT NN | project_id -> projects.id | idx_media_proxies_artifact; sqlite_autoindex_media_proxies_v6_1 U; sqlite_autoindex_media_proxies_v6_2 U |
| messages | 0 | EMPTY | id TEXT PK; conversation_id TEXT NN; role TEXT NN; content TEXT NN; metadata_json TEXT NN; created_at TEXT NN | conversation_id -> conversations.id | sqlite_autoindex_messages_1 U |
| node_runs_v3 | 0 | EMPTY | id TEXT PK; run_id TEXT NN; node_id TEXT NN; status TEXT NN; attempt INTEGER NN; input_snapshot_json TEXT NN; output_json TEXT; error_json TEXT; started_at TEXT; finished_at TEXT; created_at TEXT NN; updated_at TEXT NN | run_id -> workflow_runs_v3.id | idx_node_runs_v3_run; sqlite_autoindex_node_runs_v3_1 U |
| projects | 1 | MIGRATE | id TEXT PK; name TEXT NN; document_json TEXT NN; revision INTEGER NN; created_at TEXT NN; updated_at TEXT NN; lifecycle_status TEXT NN | none | idx_projects_lifecycle; sqlite_autoindex_projects_1 U |
| prompt_versions | 16 | ARCHIVE_ONLY | id TEXT PK; project_id TEXT NN; logical_asset_id TEXT NN; asset_class TEXT NN; version INTEGER NN; parent_version INTEGER; prompt TEXT NN; source TEXT NN; skill_id TEXT; status TEXT NN; change_reason TEXT; source_qa_run_id TEXT; rebuilt_from_failure_ids TEXT NN; created_at TEXT NN | source_qa_run_id -> asset_qa_runs.id; project_id -> projects.id | idx_prompt_versions_project_logical_version_v13; idx_prompt_versions_single_approved_v9 U; sqlite_autoindex_prompt_versions_1 U |
| provider_profiles | 4 | ARCHIVE_ONLY | id TEXT PK; provider_type TEXT NN; display_name TEXT NN; base_url TEXT NN; credential_ref TEXT; model_config_json TEXT NN; capabilities_json TEXT NN; enabled INTEGER NN; last_health_json TEXT; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_provider_profiles_1 U |
| recovery_plans_v11 | 1 | ARCHIVE_ONLY | id TEXT PK; source_project_id TEXT NN; proposed_project_id TEXT NN; proposed_name TEXT NN; status TEXT NN; manifest_json TEXT NN; manifest_sha256 TEXT NN; conflicts_json TEXT NN; detail_json TEXT NN; created_at TEXT NN; applied_at TEXT; verified_at TEXT | none | idx_recovery_plans_v11_source; sqlite_autoindex_recovery_plans_v11_1 U |
| render_jobs_v6 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; timeline_revision INTEGER NN; status TEXT NN; request_json TEXT NN; manifest_json TEXT NN; result_json TEXT; error_json TEXT; confirmed_at TEXT; started_at TEXT; finished_at TEXT; created_at TEXT NN; updated_at TEXT NN; idempotency_fingerprint TEXT; approval_consumed_at TEXT | project_id -> projects.id | idx_render_jobs_inflight_fingerprint_v10 U; idx_render_jobs_status; idx_render_jobs_project; sqlite_autoindex_render_jobs_v6_1 U |
| schema_migrations | 16 | LEGACY_ONLY | version INTEGER PK; applied_at TEXT NN | none | none |
| sqlite_sequence | 5 | LEGACY_ONLY | name; seq | none | none |
| story_versions | 0 | EMPTY | id TEXT PK; project_id TEXT NN; kind TEXT NN; parent_id TEXT; source_script_version_id TEXT; status TEXT NN; source TEXT NN; skill_id TEXT; provider_profile_id TEXT; provider_model TEXT; content_json TEXT NN; accepted_at TEXT; created_at TEXT NN | none | sqlite_autoindex_story_versions_1 U |
| story_workflow_chains | 0 | EMPTY | id TEXT PK; project_id TEXT NN; source_script_version_id TEXT; storyboard_run_id TEXT; regulator_run_id TEXT; active_step TEXT NN; status TEXT NN; provider_profile_id TEXT; provider_model TEXT; input_json TEXT NN; storyboard_output_json TEXT; regulator_output_json TEXT; error_json TEXT; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_story_workflow_chains_1 U |
| task_events | 0 | EMPTY | id INTEGER PK; task_id TEXT NN; from_status TEXT; to_status TEXT NN; detail_json TEXT NN; created_at TEXT NN | task_id -> tasks.id | none |
| tasks | 0 | EMPTY | id TEXT PK; project_id TEXT; task_type TEXT NN; status TEXT NN; provider_profile_id TEXT; provider_model TEXT; request_json TEXT NN; result_json TEXT; error_kind TEXT; error_message TEXT; paid INTEGER NN; confirmed_at TEXT; provider_task_id TEXT; attempts INTEGER NN; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_tasks_1 U |
| timeline_events_v6 | 1 | DERIVE | id INTEGER PK; project_id TEXT NN; revision INTEGER NN; event_type TEXT NN; detail_json TEXT NN; created_at TEXT NN | project_id -> projects.id | idx_timeline_events_project |
| timelines_v3 | 1 | ARCHIVE_ONLY | project_id TEXT PK; revision INTEGER NN; document_json TEXT NN; created_at TEXT NN; updated_at TEXT NN | project_id -> projects.id | sqlite_autoindex_timelines_v3_1 U |
| workflow_graph_events | 1 | DERIVE | id INTEGER PK; project_id TEXT NN; revision INTEGER NN; event_type TEXT NN; detail_json TEXT NN; created_at TEXT NN | project_id -> projects.id | idx_graph_events_project |
| workflow_graphs | 1 | ARCHIVE_ONLY | project_id TEXT PK; revision INTEGER NN; graph_json TEXT NN; created_at TEXT NN; updated_at TEXT NN | project_id -> projects.id | sqlite_autoindex_workflow_graphs_1 U |
| workflow_run_events_v3 | 0 | EMPTY | id INTEGER PK; run_id TEXT NN; node_id TEXT; event_type TEXT NN; detail_json TEXT NN; created_at TEXT NN | run_id -> workflow_runs_v3.id | idx_run_events_v3_run |
| workflow_runs | 0 | EMPTY | id TEXT PK; project_id TEXT NN; skill_id TEXT NN; skill_version TEXT NN; status TEXT NN; input_json TEXT NN; output_json TEXT; gate_result_json TEXT NN; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_workflow_runs_1 U |
| workflow_runs_v3 | 0 | EMPTY | id TEXT PK; project_id TEXT NN; graph_revision INTEGER NN; status TEXT NN; request_json TEXT NN; graph_snapshot_json TEXT NN; estimate_json TEXT NN; result_json TEXT; error_json TEXT; created_at TEXT NN; updated_at TEXT NN; idempotency_fingerprint TEXT | project_id -> projects.id | idx_workflow_runs_inflight_fingerprint_v10 U; idx_runs_v3_project; sqlite_autoindex_workflow_runs_v3_1 U |
| workflow_templates_v3 | 0 | EMPTY | id TEXT PK; name TEXT NN; description TEXT NN; category TEXT NN; version INTEGER NN; graph_json TEXT NN; builtin INTEGER NN; created_at TEXT NN; updated_at TEXT NN | none | sqlite_autoindex_workflow_templates_v3_1 U |

Inventory counts:

    MIGRATE      = 3
    DERIVE       = 4
    ARCHIVE_ONLY = 11
    LEGACY_ONLY  = 2
    EMPTY        = 21
    UNKNOWN      = 0
    TOTAL        = 41

## 3. Mapping Rules

### 3.1 Projects and embedded Shots

projects.id is preserved as V5 projects.id. name -> title. document ratio/fps/duration -> aspect_ratio/fps/target_duration. Lifecycle values use only explicit existing aliases. Missing required display values use conservative documented fallbacks and add warnings.

V3 projects.document_json.shots[] is passed through the existing scripts/migrate_shot_spec_v1_to_v2_2.py adapter into shots.shot_spec_json. id, shotId, sequence_id, and sequenceId are preserved first. Missing sequence follows the existing adapter default SQ001 instead of inventing a project ID. Every inserted shot is JSON-Schema v2.2 validated. Unknown legacy status or invalid values are recorded as UNMAPPED and remain in the legacy backup; no guessed value is written.

### 3.2 Assets and artifacts

Project JSON assets and asset_versions.logical_asset_id jointly form V5 assets. asset_versions.version, status, and artifact_id are preserved. LOCKED/approved records are not rewritten. V3 artifacts.id, project ID, local path, sha256, task ID, and confirmed shot/asset references are preserved. Files are never moved, renamed, or rewritten.

### 3.3 Tasks and events

V3 tasks.id, project, task_type, request/result/error, and attempts map to V5 tasks. Old statuses use only explicit V5 TaskState aliases. audit_events_v16, asset_events, timeline_events_v6, and workflow_graph_events derive into V5 events. Other workflow/provider/QA/recovery tables are not forced into semantically incompatible V5 rows; they remain ARCHIVE_ONLY in the consistent legacy backup.

### 3.4 Provider and generation boundaries

The production snapshot had no V3 tasks or generation rows available for provider submission. Therefore candidate generations and provider_submissions remain empty. Future generation must use V5 package_manifest_artifact_id, idempotency_key, request_hash, and shot_spec_version. No old package_id is restored and no provider submission is fabricated in T02-R.

## 4. Real Production-Copy Run Accounting

The real run was:

    production read-only source
    -> sqlite3 backup API
    -> fresh candidate
    -> Alembic online upgrade
    -> transformation
    -> schema/data validation

Temporary artifacts were under %TEMP%\frameflow-t02-prod-* and were never staged.

    source tables               = 41
    candidate domain tables     = 11
    rows migrated               = 61
    rows derived                = 160
    rows archived               = 156
    rows unmapped               = 17 embedded SH rows
    candidate integrity_check   = ok
    candidate foreign_key_check = no violations
    candidate StateStore read   = PASS
    source unchanged            = YES

SH004 through SH020 were unmapped because their old BLOCKED, PARTIAL, or MISSING statuses are outside the v2.2 enum. They remain in the consistent legacy backup and were not deleted or rewritten. This is an explicit migration gap, not a claim that every embedded shot is migrated.

## 5. Safety and Rollback

- Production source is opened read-only; consistent backup uses Python sqlite3.Connection.backup(), not a simple copy of the main DB file.
- Backup and candidate run integrity_check and foreign_key_check. Backup restore modifies only a candidate copy and then restores the original value from backup.
- Candidate runs real online upgrade head, real downgrade base, and upgrade head again. Alembic version rows change correctly at each step.
- Candidate supplied as production, restore target supplied as production, existing candidate overwrite, corrupt input, bad FK, and schema drift are failure-tested.
- T02-R does not switch ownership in server.py, frameflow/database.py, frameflow/runtime.py, or core/runtime/state_store. Atomic cutover, compatibility bridge, restart, and rollback remain T03-R work.
