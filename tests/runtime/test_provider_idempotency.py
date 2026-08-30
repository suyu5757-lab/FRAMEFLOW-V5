from __future__ import annotations

import threading
import tempfile
from pathlib import Path
from unittest import TestCase

from sqlalchemy.exc import IntegrityError

from core.runtime.idempotency import (
    GenerationNotFoundError,
    ProviderIdempotencyService,
    ProviderSubmitTimeout,
    ProviderSubmissionStore,
    SubmissionConflictError,
    SubmissionStatus,
    SubmitAction,
    idempotency_key,
    provider_config_hash,
    request_hash,
)
from core.runtime.state_store import StateStore


class FakeProvider:
    def __init__(self) -> None:
        self.submit_count = 0
        self._lock = threading.Lock()

    def submit(self, request_payload):
        with self._lock:
            self.submit_count += 1
            return f"MOCK_EXT_{self.submit_count}"


class BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def submit(self, request_payload):
        result = super().submit(request_payload)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test did not release provider")
        return result


class TimeoutAfterRemoteSideEffectProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.reconcile_count = 0
        self.external_task_id = "MOCK_TIMEOUT_EXT_1"

    def submit(self, request_payload):
        with self._lock:
            self.submit_count += 1
        raise ProviderSubmitTimeout("response lost after remote job creation")

    def reconcile(self, request_payload, submission):
        self.reconcile_count += 1
        return self.external_task_id


class ProviderIdempotencyTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-provider-idempotency-t09-")
        self.database_path = Path(self.temp_dir.name) / "provider-idempotency.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.state_store.create_project("PRJ_T09", "T09 Project", "16:9", 24, 12)
        self.state_store.create_sequence("SQ_T09", "PRJ_T09", 0)
        self.state_store.create_shot(
            "SH_T09",
            "PRJ_T09",
            "SQ_T09",
            {"purpose": "provider idempotency test"},
        )
        self.state_store.create_artifact(
            "ART_T09_PACKAGE",
            "PRJ_T09",
            "package_manifest",
            "manifest",
            "projects/PRJ_T09/packages/v01.json",
            "v01",
            shot_id="SH_T09",
        )
        self.state_store.create_generation(
            "GEN_T09",
            "SH_T09",
            "ART_T09_PACKAGE",
            "mock",
        )
        self.submissions = ProviderSubmissionStore(self.state_store)
        self.service = ProviderIdempotencyService(self.submissions)
        self.provider_config = {"duration": 5, "model": "mock-v1", "options": {"quality": "draft"}}
        self.request_payload = {
            "duration": 5,
            "prompt": "a deterministic test shot",
            "references": ["ART_T09_PACKAGE"],
            "provider_parameters": {"seed": 7, "quality": "draft"},
        }

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def service_kwargs(self, provider, **changes):
        values = {
            "generation_id": "GEN_T09",
            "project_id": "PRJ_T09",
            "shot_id": "SH_T09",
            "package_version": "v01",
            "shot_spec_version": "v1",
            "provider": "mock",
            "provider_config": self.provider_config,
            "request_payload": self.request_payload,
            "submitter": provider,
        }
        values.update(changes)
        return values

    def test_t09_01_sequential_double_click_creates_one_external_job(self) -> None:
        provider = FakeProvider()
        first = self.service.submit(**self.service_kwargs(provider))
        second = self.service.submit(**self.service_kwargs(provider))

        self.assertEqual(SubmitAction.SUBMITTED, first.action)
        self.assertEqual(SubmitAction.REUSED, second.action)
        self.assertEqual(1, provider.submit_count)
        self.assertEqual(first.submission["id"], second.submission["id"])
        self.assertEqual(SubmissionStatus.SUBMITTED.value, second.submission["status"])
        self.assertEqual("MOCK_EXT_1", second.submission["external_task_id"])
        self.assertEqual(1, second.submission["attempt"])

    def test_t09_02_concurrent_double_click_elects_one_submitter(self) -> None:
        provider = BlockingProvider()
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        service_a = ProviderIdempotencyService(ProviderSubmissionStore(store_a))
        service_b = ProviderIdempotencyService(ProviderSubmissionStore(store_b))
        results: list = []
        errors: list[BaseException] = []
        duplicate_done = threading.Event()

        def owner_run() -> None:
            try:
                results.append(service_a.submit(**self.service_kwargs(provider)))
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        def duplicate_run() -> None:
            try:
                if not provider.started.wait(timeout=5):
                    raise RuntimeError("owner did not reach provider")
                results.append(service_b.submit(**self.service_kwargs(provider)))
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)
            finally:
                duplicate_done.set()

        first = threading.Thread(target=owner_run)
        second = threading.Thread(target=duplicate_run)
        try:
            first.start()
            second.start()
            self.assertTrue(provider.started.wait(timeout=5))
            self.assertTrue(duplicate_done.wait(timeout=5))
            provider.release.set()
            first.join(timeout=8)
            second.join(timeout=8)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(1, provider.submit_count)
            self.assertEqual(2, len(results))
            self.assertIn(SubmitAction.IN_PROGRESS, {result.action for result in results})
            self.assertEqual(
                SubmissionStatus.SUBMITTED.value,
                self.submissions.get_by_idempotency_key(results[0].idempotency_key)["status"],
            )
        finally:
            store_a.close()
            store_b.close()

    def test_t09_03_timeout_after_remote_side_effect_reconciles_without_resubmit(self) -> None:
        provider = TimeoutAfterRemoteSideEffectProvider()
        result = self.service.submit(**self.service_kwargs(provider))

        self.assertEqual(SubmitAction.RECONCILED, result.action)
        self.assertEqual(1, provider.submit_count)
        self.assertEqual(1, provider.reconcile_count)
        self.assertEqual("MOCK_TIMEOUT_EXT_1", result.submission["external_task_id"])
        self.assertEqual(SubmissionStatus.SUBMITTED.value, result.submission["status"])

    def test_t09_04_deterministic_key_survives_new_service_instance(self) -> None:
        config_hash = provider_config_hash({"b": 2, "a": 1})
        first = idempotency_key(
            project_id="PRJ_T09",
            shot_id="SH_T09",
            package_version="v01",
            shot_spec_version="v1",
            provider="mock",
            provider_config_hash=config_hash,
        )
        second = idempotency_key(
            project_id="PRJ_T09",
            shot_id="SH_T09",
            package_version="v01",
            shot_spec_version="v1",
            provider="mock",
            provider_config_hash=config_hash,
        )
        self.assertEqual(first, second)
        self.assertEqual(64, len(request_hash(self.request_payload)))

    def test_t09_05_shot_spec_version_changes_key(self) -> None:
        config_hash = provider_config_hash(self.provider_config)
        common = {
            "project_id": "PRJ_T09",
            "shot_id": "SH_T09",
            "package_version": "v01",
            "provider": "mock",
            "provider_config_hash": config_hash,
        }
        self.assertNotEqual(
            idempotency_key(**common, shot_spec_version="v1"),
            idempotency_key(**common, shot_spec_version="v2"),
        )

    def test_t09_06_package_version_changes_key(self) -> None:
        config_hash = provider_config_hash(self.provider_config)
        common = {
            "project_id": "PRJ_T09",
            "shot_id": "SH_T09",
            "shot_spec_version": "v1",
            "provider": "mock",
            "provider_config_hash": config_hash,
        }
        self.assertNotEqual(
            idempotency_key(**common, package_version="v01"),
            idempotency_key(**common, package_version="v02"),
        )

    def test_t09_07_provider_changes_key(self) -> None:
        config_hash = provider_config_hash(self.provider_config)
        common = {
            "project_id": "PRJ_T09",
            "shot_id": "SH_T09",
            "package_version": "v01",
            "shot_spec_version": "v1",
            "provider_config_hash": config_hash,
        }
        self.assertNotEqual(
            idempotency_key(**common, provider="mock"),
            idempotency_key(**common, provider="other-mock"),
        )

    def test_t09_08_provider_config_changes_key(self) -> None:
        common = {
            "project_id": "PRJ_T09",
            "shot_id": "SH_T09",
            "package_version": "v01",
            "shot_spec_version": "v1",
            "provider": "mock",
        }
        self.assertNotEqual(
            idempotency_key(**common, provider_config_hash=provider_config_hash({"model": "a"})),
            idempotency_key(**common, provider_config_hash=provider_config_hash({"model": "b"})),
        )

    def test_t09_09_provider_config_key_order_is_canonical(self) -> None:
        self.assertEqual(
            provider_config_hash({"a": 1, "b": 2}),
            provider_config_hash({"b": 2, "a": 1}),
        )

    def test_t09_10_request_hash_key_order_is_canonical(self) -> None:
        self.assertEqual(
            request_hash({"prompt": "x", "parameters": {"a": 1, "b": 2}}),
            request_hash({"parameters": {"b": 2, "a": 1}, "prompt": "x"}),
        )

    def test_t09_11_same_key_different_request_hash_is_rejected(self) -> None:
        provider = FakeProvider()
        self.service.submit(**self.service_kwargs(provider))
        changed_request = {**self.request_payload, "prompt": "different actual request"}
        with self.assertRaises(SubmissionConflictError):
            self.service.submit(**self.service_kwargs(provider, request_payload=changed_request))
        self.assertEqual(1, provider.submit_count)

    def test_t09_12_restart_reuses_persisted_submission(self) -> None:
        provider = FakeProvider()
        first = self.service.submit(**self.service_kwargs(provider))
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.submissions = ProviderSubmissionStore(self.state_store)
        self.service = ProviderIdempotencyService(self.submissions)
        second = self.service.submit(**self.service_kwargs(provider))

        self.assertEqual(SubmitAction.SUBMITTED, first.action)
        self.assertEqual(SubmitAction.REUSED, second.action)
        self.assertEqual(1, provider.submit_count)
        self.assertEqual(first.submission["id"], second.submission["id"])

    def test_t09_13_intent_transaction_failure_leaves_no_submission(self) -> None:
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_provider_intent "
                "BEFORE INSERT ON provider_submissions "
                "BEGIN SELECT RAISE(ABORT, 'provider intent failure'); END"
            )
        provider = FakeProvider()
        try:
            with self.assertRaises(IntegrityError):
                self.service.submit(**self.service_kwargs(provider))
            with self.state_store.connection() as connection:
                count = connection.exec_driver_sql("SELECT COUNT(*) FROM provider_submissions").scalar()
            self.assertEqual(0, count)
            self.assertEqual(0, provider.submit_count)
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_provider_intent")

    def test_t09_14_bind_transaction_failure_does_not_fake_submitted(self) -> None:
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_provider_bind "
                "BEFORE UPDATE OF status ON provider_submissions "
                "WHEN NEW.status = 'SUBMITTED' "
                "BEGIN SELECT RAISE(ABORT, 'provider bind failure'); END"
            )
        provider = FakeProvider()
        try:
            with self.assertRaises(IntegrityError):
                self.service.submit(**self.service_kwargs(provider))
            with self.state_store.connection() as connection:
                row = connection.exec_driver_sql(
                    "SELECT status, external_task_id, attempt FROM provider_submissions"
                ).first()
            self.assertEqual((SubmissionStatus.SUBMITTING.value, None, 1), tuple(row))
            self.assertEqual(1, provider.submit_count)
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_provider_bind")

    def test_t09_15_missing_generation_is_rejected_before_external_submit(self) -> None:
        provider = FakeProvider()
        with self.assertRaises(GenerationNotFoundError):
            self.service.submit(**self.service_kwargs(provider, generation_id="GEN_MISSING"))
        self.assertEqual(0, provider.submit_count)

    def test_t09_16_same_request_hash_with_different_key_is_not_globally_deduped(self) -> None:
        provider = FakeProvider()
        first = self.service.submit(**self.service_kwargs(provider, package_version="v01"))
        second = self.service.submit(**self.service_kwargs(provider, package_version="v02"))

        self.assertNotEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(first.request_hash, second.request_hash)
        self.assertEqual(2, provider.submit_count)
        self.assertNotEqual(first.submission["id"], second.submission["id"])


if __name__ == "__main__":
    import unittest

    unittest.main()
