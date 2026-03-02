from pathlib import Path

from assert_utils import AssertMixin
from app.infrastructure.config import Config
from app.domain.task_error_key import normalize_error_key
from app.domain.task_store import TASK_DONE
from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.interfaces.http import create_app


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_task_query_api"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


def make_config():
    return Config.from_dict({"miniflux": {}, "llm": {"max_workers": 1}})


class TestTaskQueryAPI(AssertMixin):
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def _build_app(self, task_store=None):
        return create_app(
            config=make_config(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=task_store,
        )

    def test_list_tasks_supports_pagination(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_pagination.db"))
        task_store.create_task("canon-1", {"entry_id": 1}, "trace-1", now_ts=1000)
        task_store.create_task("canon-2", {"entry_id": 2}, "trace-2", now_ts=1001)
        task_store.create_task("canon-3", {"entry_id": 3}, "trace-3", now_ts=1002)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?limit=2&offset=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["offset"], 1)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["total"], 3)
        self.assertFalse(payload["include_payload"])
        self.assertEqual(payload["tasks"][0]["canonical_id"], "canon-2")
        self.assertEqual(payload["tasks"][1]["canonical_id"], "canon-3")
        self.assertNotIn("payload", payload["tasks"][0])
        self.assertNotIn("payload", payload["tasks"][1])

    def test_list_tasks_can_include_payload(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_with_payload.db"))
        task_store.create_task("canon-1", {"entry_id": 1}, "trace-1", now_ts=1000)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?include_payload=true")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["include_payload"])
        self.assertEqual(payload["tasks"][0]["payload"], {"entry_id": 1})

    def test_list_tasks_supports_status_filter(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_filter.db"))
        task_store.create_task("canon-done", {"entry_id": 1}, "trace-1", now_ts=1000)
        task_store.create_task("canon-pending", {"entry_id": 2}, "trace-2", now_ts=1001)
        claimed = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)
        self.assertEqual(len(claimed), 1)
        task_store.mark_done(claimed[0].id, now_ts=2001)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?status=done")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["status_filter"], "done")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["tasks"][0]["canonical_id"], "canon-done")
        self.assertEqual(payload["tasks"][0]["status"], TASK_DONE)

    def test_list_tasks_returns_400_for_invalid_status(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_invalid_status.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?status=unknown")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid status"},
        )

    def test_list_tasks_returns_400_for_invalid_limit(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_invalid_limit.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid limit"},
        )

    def test_list_tasks_returns_400_for_invalid_include_payload(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_invalid_include_payload.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks?include_payload=maybe")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid include_payload"},
        )

    def test_list_tasks_returns_500_when_task_query_fails(self):
        class FailingTaskStore:
            def list_tasks(self, **kwargs):
                raise RuntimeError("query failed")

            def count_tasks(self, **kwargs):
                return 0

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task query failed"},
        )

    def test_get_task_returns_task_detail(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_get.db"))
        task_store.create_task("canon-1", {"entry_id": 101}, "trace-1", now_ts=1000)
        created = task_store.list_tasks(limit=1, offset=0)[0]
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get(f"/miniflux-ai/user/tasks/{created.id}")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["task"]["id"], created.id)
        self.assertEqual(payload["task"]["canonical_id"], "canon-1")
        self.assertEqual(payload["task"]["trace_id"], "trace-1")
        self.assertEqual(payload["task"]["payload"], {"entry_id": 101})

    def test_get_task_returns_404_when_task_not_found(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_not_found.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"status": "not_found", "task_id": "999"},
        )

    def test_get_task_returns_400_for_invalid_task_id(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_invalid_id.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid task_id"},
        )

    def test_get_task_returns_500_when_task_query_fails(self):
        class FailingTaskStore:
            def get_task(self, task_id):
                raise RuntimeError("query failed")

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/1")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task query failed"},
        )

    def test_task_metrics_returns_status_counts(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_metrics.db"))

        task_store.create_task("canon-done", {"entry_id": 1}, "trace-1", now_ts=1000)
        done_task = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_done(done_task.id, now_ts=2001)

        task_store.create_task("canon-retry", {"entry_id": 2}, "trace-2", now_ts=1001)
        retry_task = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(
            retry_task.id, "temporary error", retry_delay_seconds=30, now_ts=2003
        )

        task_store.create_task(
            "canon-dead",
            {"entry_id": 3},
            "trace-3",
            max_attempts=1,
            now_ts=1002,
        )
        dead_task = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        task_store.mark_retryable(
            dead_task.id, "permanent failure", retry_delay_seconds=30, now_ts=2005
        )

        task_store.create_task("canon-pending", {"entry_id": 4}, "trace-4", now_ts=1003)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["backlog"], 2)
        self.assertEqual(payload["time"]["throughput_window_seconds"], 300)
        self.assertEqual(payload["counts"]["pending"], 1)
        self.assertEqual(payload["counts"]["running"], 0)
        self.assertEqual(payload["counts"]["retryable"], 1)
        self.assertEqual(payload["counts"]["dead"], 1)
        self.assertEqual(payload["counts"]["done"], 1)
        self.assertEqual(payload["counts"]["ready_to_claim"], 2)
        self.assertEqual(payload["counts"]["delayed_retry"], 0)
        self.assertEqual(payload["flow"]["done_window"], 0)
        self.assertEqual(payload["flow"]["dead_window"], 0)
        self.assertEqual(payload["flow"]["terminal_failure_rate"], 0.5)
        self.assertEqual(payload["flow"]["terminal_failure_rate_window"], 0.0)
        self.assertEqual(payload["retries"]["retries_total_estimated"], 0)
        self.assertEqual(payload["retries"]["avg_attempts_done"], 1.0)
        self.assertEqual(payload["retries"]["avg_attempts_dead"], 1.0)

    def test_task_metrics_returns_500_when_task_query_fails(self):
        class FailingTaskStore:
            def get_metrics(self, **kwargs):
                raise RuntimeError("query failed")

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/metrics")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task query failed"},
        )

    def test_failure_groups_returns_aggregated_rows(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups.db"))

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(
            r1.id, "network timeout", retry_delay_seconds=60, now_ts=2001
        )

        task_store.create_task("canon-r2", {"entry_id": 2}, "trace-2", now_ts=1001)
        r2 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(
            r2.id, "network timeout", retry_delay_seconds=60, now_ts=2003
        )

        task_store.create_task(
            "canon-d1",
            {"entry_id": 3},
            "trace-3",
            max_attempts=1,
            now_ts=1002,
        )
        d1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        task_store.mark_retryable(
            d1.id, "invalid payload", retry_delay_seconds=60, now_ts=2005
        )

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/failure-groups")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["groups"][0]["status"], "retryable")
        self.assertEqual(payload["groups"][0]["error_key"], "network timeout")
        self.assertEqual(payload["groups"][0]["error"], "network timeout")
        self.assertEqual(payload["groups"][0]["count"], 2)

    def test_failure_groups_returns_500_when_task_query_fails(self):
        class FailingTaskStore:
            def list_failure_groups(self, **kwargs):
                raise RuntimeError("query failed")

            def count_failure_groups(self, **kwargs):
                return 0

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/failure-groups")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task query failed"},
        )

    def test_failure_groups_supports_status_filter(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups_filter.db"))

        task_store.create_task("canon-r", {"entry_id": 1}, "trace-1", now_ts=1000)
        r = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(r.id, "retry error", retry_delay_seconds=60, now_ts=2001)

        task_store.create_task(
            "canon-d",
            {"entry_id": 2},
            "trace-2",
            max_attempts=1,
            now_ts=1001,
        )
        d = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(d.id, "dead error", retry_delay_seconds=60, now_ts=2003)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/failure-groups?status=dead")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status_filter"], "dead")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["groups"][0]["status"], "dead")
        self.assertEqual(payload["groups"][0]["error_key"], "dead error")
        self.assertEqual(payload["groups"][0]["error"], "dead error")

    def test_failure_groups_supports_error_normalization_filter(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups_error_filter.db"))

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(
            r1.id, "upstream timeout for entry 123", retry_delay_seconds=60, now_ts=2001
        )

        task_store.create_task("canon-r2", {"entry_id": 2}, "trace-2", now_ts=1001)
        r2 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(
            r2.id, "upstream timeout for entry 456", retry_delay_seconds=60, now_ts=2003
        )

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get(
                "/miniflux-ai/user/tasks/failure-groups?error=upstream timeout for entry 999"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["error_key_filter"],
            normalize_error_key("upstream timeout for entry 999"),
        )
        self.assertEqual(payload["groups"][0]["count"], 2)

    def test_failure_group_tasks_returns_filtered_items(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_group_tasks.db"))

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(
            r1.id, "upstream timeout for entry 111", retry_delay_seconds=60, now_ts=2001
        )

        task_store.create_task("canon-r2", {"entry_id": 2}, "trace-2", now_ts=1001)
        r2 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(
            r2.id, "upstream timeout for entry 222", retry_delay_seconds=60, now_ts=2003
        )

        task_store.create_task("canon-r3", {"entry_id": 3}, "trace-3", now_ts=1002)
        r3 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        task_store.mark_retryable(
            r3.id, "different error", retry_delay_seconds=60, now_ts=2005
        )

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get(
                "/miniflux-ai/user/tasks/failure-groups/tasks?status=retryable&error=upstream timeout for entry 999"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        expected_key = normalize_error_key("upstream timeout for entry 999")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["status_filter"], "retryable")
        self.assertEqual(payload["error_key_filter"], expected_key)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["count"], 2)
        self.assertFalse(payload["include_payload"])
        self.assertEqual(payload["tasks"][0]["error_key"], expected_key)
        self.assertEqual(payload["tasks"][1]["error_key"], expected_key)
        self.assertNotIn("payload", payload["tasks"][0])

    def test_failure_group_tasks_returns_500_when_task_query_fails(self):
        class FailingTaskStore:
            def list_failed_tasks(self, **kwargs):
                raise RuntimeError("query failed")

            def count_failed_tasks(self, **kwargs):
                return 0

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.get(
                "/miniflux-ai/user/tasks/failure-groups/tasks?status=retryable"
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task query failed"},
        )

    def test_failure_group_tasks_supports_include_payload(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_group_tasks_payload.db"))
        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(
            r1.id, "network timeout", retry_delay_seconds=60, now_ts=2001
        )

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.get(
                "/miniflux-ai/user/tasks/failure-groups/tasks?status=retryable&error_key=network timeout&include_payload=true"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["include_payload"])
        self.assertEqual(payload["tasks"][0]["payload"], {"entry_id": 1})

    def test_failure_group_tasks_returns_400_for_invalid_status(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_group_tasks_invalid.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/failure-groups/tasks?status=done")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid failure status"},
        )

    def test_failure_groups_requeue_endpoint_requeues_filtered_group(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups_requeue.db"))

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(
            r1.id, "upstream timeout for entry 111", retry_delay_seconds=60, now_ts=2001
        )

        task_store.create_task("canon-r2", {"entry_id": 2}, "trace-2", now_ts=1001)
        r2 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(
            r2.id, "upstream timeout for entry 222", retry_delay_seconds=60, now_ts=2003
        )

        task_store.create_task("canon-r3", {"entry_id": 3}, "trace-3", now_ts=1002)
        r3 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        task_store.mark_retryable(r3.id, "different error", retry_delay_seconds=60, now_ts=2005)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/failure-groups/requeue",
                json={
                    "status": "retryable",
                    "error": "upstream timeout for entry 999",
                    "limit": 10,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["requeued"], 2)
        self.assertEqual(payload["status_filter"], "retryable")
        self.assertEqual(
            payload["error_key_filter"],
            normalize_error_key("upstream timeout for entry 999"),
        )
        self.assertEqual(task_store.get_task(r1.id).status, "pending")
        self.assertEqual(task_store.get_task(r2.id).status, "pending")
        self.assertEqual(task_store.get_task(r3.id).status, "retryable")

    def test_failure_groups_requeue_endpoint_supports_status_none(self):
        task_store = TaskStoreSQLite(
            path=str(TMP_DIR / "tasks_failure_groups_requeue_status_none.db")
        )

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(r1.id, "network timeout", retry_delay_seconds=60, now_ts=2001)

        task_store.create_task(
            "canon-d1",
            {"entry_id": 2},
            "trace-2",
            max_attempts=1,
            now_ts=1001,
        )
        d1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(d1.id, "invalid payload", retry_delay_seconds=60, now_ts=2003)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/failure-groups/requeue",
                json={"limit": 10},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["status_filter"], None)
        self.assertEqual(payload["requeued"], 2)
        self.assertEqual(task_store.get_task(r1.id).status, "pending")
        self.assertEqual(task_store.get_task(d1.id).status, "pending")

    def test_failure_groups_requeue_endpoint_returns_400_for_invalid_status(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups_requeue_invalid.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/failure-groups/requeue",
                json={"status": "done"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid failure status"},
        )

    def test_failure_groups_requeue_returns_500_when_task_update_fails(self):
        class FailingTaskStore:
            def requeue_tasks(self, **kwargs):
                raise RuntimeError("update failed")

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/failure-groups/requeue",
                json={"status": "retryable"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task update failed"},
        )

    def test_failure_groups_returns_400_for_invalid_status(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_failure_groups_invalid.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/failure-groups?status=done")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid failure status"},
        )

    def test_requeue_task_endpoint_moves_task_to_pending(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_requeue_single_api.db"))
        task_store.create_task(
            "canon-dead",
            {"entry_id": 1},
            "trace-1",
            max_attempts=1,
            now_ts=1000,
        )
        dead_task = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(dead_task.id, "invalid payload", retry_delay_seconds=30, now_ts=2001)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.post(f"/miniflux-ai/user/tasks/{dead_task.id}/requeue")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["task_id"], str(dead_task.id))
        self.assertTrue(payload["requeued"])
        refreshed = task_store.get_task(dead_task.id)
        self.assertEqual(refreshed.status, "pending")

    def test_requeue_task_endpoint_returns_500_when_task_update_fails(self):
        class FailingTaskStore:
            def requeue_task(self, task_id):
                raise RuntimeError("update failed")

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.post("/miniflux-ai/user/tasks/1/requeue")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task update failed"},
        )

    def test_requeue_task_endpoint_returns_404_when_task_not_found(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_requeue_single_not_found.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.post("/miniflux-ai/user/tasks/999/requeue")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"status": "not_found", "task_id": "999"},
        )

    def test_requeue_tasks_batch_endpoint_supports_filter(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_requeue_batch_api.db"))

        task_store.create_task("canon-r1", {"entry_id": 1}, "trace-1", now_ts=1000)
        r1 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_retryable(r1.id, "network timeout", retry_delay_seconds=30, now_ts=2001)

        task_store.create_task("canon-r2", {"entry_id": 2}, "trace-2", now_ts=1001)
        r2 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        task_store.mark_retryable(r2.id, "network timeout", retry_delay_seconds=30, now_ts=2003)

        task_store.create_task("canon-r3", {"entry_id": 3}, "trace-3", now_ts=1002)
        r3 = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        task_store.mark_retryable(r3.id, "rate limited", retry_delay_seconds=30, now_ts=2005)

        app = self._build_app(task_store=task_store)
        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/requeue",
                json={"status": "retryable", "error": "network timeout", "limit": 10},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["requeued"], 2)
        self.assertEqual(payload["status_filter"], "retryable")
        self.assertEqual(payload["error_key_filter"], "network timeout")
        self.assertEqual(task_store.get_task(r1.id).status, "pending")
        self.assertEqual(task_store.get_task(r2.id).status, "pending")
        self.assertEqual(task_store.get_task(r3.id).status, "retryable")

    def test_requeue_tasks_batch_returns_400_for_invalid_status(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_requeue_batch_invalid.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/user/tasks/requeue",
                json={"status": "done"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid requeue status"},
        )

    def test_requeue_tasks_batch_returns_500_when_task_update_fails(self):
        class FailingTaskStore:
            def requeue_tasks(self, **kwargs):
                raise RuntimeError("update failed")

        app = self._build_app(task_store=FailingTaskStore())

        with app.test_client() as client:
            response = client.post("/miniflux-ai/user/tasks/requeue", json={})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task update failed"},
        )

    def test_task_metrics_supports_window_seconds(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_metrics_window.db"))
        task_store.create_task("canon-1", {"entry_id": 1}, "trace-1", now_ts=1000)
        task = task_store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        task_store.mark_done(task.id, now_ts=2001)
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/metrics?window_seconds=60")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["time"]["throughput_window_seconds"], 60)
        self.assertEqual(payload["flow"]["done_window"], 0)

    def test_task_metrics_returns_400_for_invalid_window_seconds(self):
        task_store = TaskStoreSQLite(path=str(TMP_DIR / "tasks_metrics_invalid_window.db"))
        app = self._build_app(task_store=task_store)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/tasks/metrics?window_seconds=10")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid window_seconds"},
        )

    def test_task_query_returns_500_when_task_store_missing(self):
        app = self._build_app(task_store=None)

        with app.test_client() as client:
            list_response = client.get("/miniflux-ai/user/tasks")
            metrics_response = client.get("/miniflux-ai/user/tasks/metrics")
            failure_groups_response = client.get("/miniflux-ai/user/tasks/failure-groups")
            failure_group_tasks_response = client.get(
                "/miniflux-ai/user/tasks/failure-groups/tasks"
            )
            failure_groups_requeue_response = client.post(
                "/miniflux-ai/user/tasks/failure-groups/requeue", json={}
            )
            detail_response = client.get("/miniflux-ai/user/tasks/1")
            requeue_single_response = client.post("/miniflux-ai/user/tasks/1/requeue")
            requeue_batch_response = client.post("/miniflux-ai/user/tasks/requeue", json={})

        self.assertEqual(list_response.status_code, 500)
        self.assertEqual(
            list_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(detail_response.status_code, 500)
        self.assertEqual(
            detail_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(metrics_response.status_code, 500)
        self.assertEqual(
            metrics_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(failure_groups_response.status_code, 500)
        self.assertEqual(
            failure_groups_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(failure_group_tasks_response.status_code, 500)
        self.assertEqual(
            failure_group_tasks_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(failure_groups_requeue_response.status_code, 500)
        self.assertEqual(
            failure_groups_requeue_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(requeue_single_response.status_code, 500)
        self.assertEqual(
            requeue_single_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
        self.assertEqual(requeue_batch_response.status_code, 500)
        self.assertEqual(
            requeue_batch_response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )
