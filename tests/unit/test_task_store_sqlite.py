from pathlib import Path

from assert_utils import AssertMixin
from common.task_error_key import normalize_error_key
from common.task_store import TASK_DEAD, TASK_DONE, TASK_RETRYABLE, TASK_RUNNING
from common.task_store_sqlite import TaskStoreSQLite


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_task_store_sqlite"


class TestTaskStoreSQLite(AssertMixin):
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_create_task_is_idempotent_by_canonical_id(self):
        path = TMP_DIR / "tasks_idempotent.db"
        store = TaskStoreSQLite(path=str(path))

        created_a = store.create_task(
            canonical_id="canon-1",
            payload={"entry_id": 101},
            trace_id="trace-1",
            now_ts=1000,
        )
        created_b = store.create_task(
            canonical_id="canon-1",
            payload={"entry_id": 102},
            trace_id="trace-2",
            now_ts=1001,
        )

        self.assertTrue(created_a)
        self.assertFalse(created_b)
        rows = store.list_tasks()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].canonical_id, "canon-1")
        self.assertEqual(rows[0].payload["entry_id"], 101)
        self.assertEqual(rows[0].trace_id, "trace-1")

    def test_claim_marks_running_and_increments_attempts(self):
        path = TMP_DIR / "tasks_claim.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task("canon-1", {"x": 1}, "t-1", now_ts=1000)
        store.create_task("canon-2", {"x": 2}, "t-2", now_ts=1001)

        claimed = store.claim_tasks(limit=1, lease_seconds=30, now_ts=2000)

        self.assertEqual(len(claimed), 1)
        task = claimed[0]
        self.assertEqual(task.status, TASK_RUNNING)
        self.assertEqual(task.attempts, 1)
        self.assertEqual(task.leased_until, 2030)

    def test_mark_done_prevents_reclaim(self):
        path = TMP_DIR / "tasks_done.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task("canon-1", {"x": 1}, "t-1", now_ts=1000)
        claimed = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)
        self.assertEqual(len(claimed), 1)

        task_id = claimed[0].id
        store.mark_done(task_id, now_ts=2001)
        task = store.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TASK_DONE)

        reclaimed = store.claim_tasks(limit=10, lease_seconds=10, now_ts=3000)
        self.assertEqual(len(reclaimed), 0)

    def test_mark_retryable_respects_retry_delay(self):
        path = TMP_DIR / "tasks_retry.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task("canon-1", {"x": 1}, "t-1", now_ts=1000)
        claimed = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)
        task_id = claimed[0].id

        store.mark_retryable(task_id, "temporary error", retry_delay_seconds=15, now_ts=2001)
        task = store.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TASK_RETRYABLE)
        self.assertEqual(task.next_retry_at, 2016)

        before_ready = store.claim_tasks(limit=1, now_ts=2010)
        self.assertEqual(len(before_ready), 0)
        after_ready = store.claim_tasks(limit=1, now_ts=2017)
        self.assertEqual(len(after_ready), 1)
        self.assertEqual(after_ready[0].id, task_id)

    def test_mark_retryable_turns_dead_when_attempts_exhausted(self):
        path = TMP_DIR / "tasks_dead.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task(
            canonical_id="canon-1",
            payload={"x": 1},
            trace_id="t-1",
            max_attempts=1,
            now_ts=1000,
        )
        claimed = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)
        task_id = claimed[0].id

        store.mark_retryable(task_id, "still failing", retry_delay_seconds=1, now_ts=2001)
        task = store.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, TASK_DEAD)
        self.assertEqual(task.last_error, "still failing")
        self.assertEqual(task.error_key, "still failing")

        should_not_claim = store.claim_tasks(limit=1, now_ts=3000)
        self.assertEqual(len(should_not_claim), 0)

    def test_claim_can_recover_expired_running_lease(self):
        path = TMP_DIR / "tasks_lease_recover.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task("canon-1", {"x": 1}, "t-1", now_ts=1000)

        first = store.claim_tasks(limit=1, lease_seconds=5, now_ts=2000)
        self.assertEqual(len(first), 1)
        task_id = first[0].id
        self.assertEqual(first[0].attempts, 1)

        before_expire = store.claim_tasks(limit=1, lease_seconds=5, now_ts=2004)
        self.assertEqual(len(before_expire), 0)

        after_expire = store.claim_tasks(limit=1, lease_seconds=5, now_ts=2006)
        self.assertEqual(len(after_expire), 1)
        self.assertEqual(after_expire[0].id, task_id)
        self.assertEqual(after_expire[0].attempts, 2)

    def test_count_tasks_and_count_by_status(self):
        path = TMP_DIR / "tasks_counts.db"
        store = TaskStoreSQLite(path=str(path))
        store.create_task("canon-done", {"x": 1}, "t-1", now_ts=1000)
        done_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_done(done_task.id, now_ts=2001)

        store.create_task("canon-retry", {"x": 2}, "t-2", now_ts=1001)
        retry_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(retry_task.id, "temporary", retry_delay_seconds=30, now_ts=2003)

        store.create_task("canon-pending", {"x": 3}, "t-3", now_ts=1002)

        self.assertEqual(store.count_tasks(), 3)
        self.assertEqual(store.count_tasks(status="done"), 1)
        self.assertEqual(store.count_tasks(status="retryable"), 1)
        self.assertEqual(store.count_tasks(status="pending"), 1)
        self.assertEqual(store.count_tasks(status="running"), 0)
        self.assertEqual(store.count_tasks(status="dead"), 0)

        counts = store.count_tasks_by_status()
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["retryable"], 1)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["running"], 0)
        self.assertEqual(counts["dead"], 0)

    def test_get_metrics_returns_aggregates(self):
        path = TMP_DIR / "tasks_metrics.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-done", {"x": 1}, "t-1", now_ts=1000)
        done_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_done(done_task.id, now_ts=2001)

        store.create_task("canon-retry", {"x": 2}, "t-2", now_ts=1001)
        retry_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(retry_task.id, "temporary", retry_delay_seconds=40, now_ts=2003)
        retry_task_2 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2044)[0]
        self.assertEqual(retry_task_2.id, retry_task.id)
        store.mark_retryable(
            retry_task_2.id, "temporary-again", retry_delay_seconds=100, now_ts=2045
        )

        store.create_task(
            "canon-dead",
            {"x": 3},
            "t-3",
            max_attempts=1,
            now_ts=1002,
        )
        dead_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        store.mark_retryable(dead_task.id, "still failing", retry_delay_seconds=5, now_ts=2005)

        store.create_task("canon-pending", {"x": 4}, "t-4", now_ts=1003)

        metrics = store.get_metrics(now_ts=2100, throughput_window_seconds=300)

        self.assertEqual(metrics["time"]["throughput_window_seconds"], 300)
        self.assertEqual(metrics["counts"]["total"], 4)
        self.assertEqual(metrics["counts"]["backlog"], 2)
        self.assertEqual(metrics["counts"]["pending"], 1)
        self.assertEqual(metrics["counts"]["running"], 0)
        self.assertEqual(metrics["counts"]["retryable"], 1)
        self.assertEqual(metrics["counts"]["dead"], 1)
        self.assertEqual(metrics["counts"]["done"], 1)
        self.assertEqual(metrics["counts"]["ready_to_claim"], 1)
        self.assertEqual(metrics["counts"]["delayed_retry"], 1)
        self.assertEqual(metrics["flow"]["done_window"], 1)
        self.assertEqual(metrics["flow"]["dead_window"], 1)
        self.assertEqual(metrics["flow"]["terminal_failure_rate"], 0.5)
        self.assertEqual(metrics["flow"]["terminal_failure_rate_window"], 0.5)
        self.assertEqual(metrics["retries"]["retries_total_estimated"], 1)
        self.assertEqual(metrics["latency"]["oldest_backlog_age_seconds"], 1099)

    def test_failure_groups_aggregate_retryable_and_dead(self):
        path = TMP_DIR / "tasks_failure_groups.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-r1", {"x": 1}, "t-1", now_ts=1000)
        r1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(r1.id, "network timeout", retry_delay_seconds=60, now_ts=2001)

        store.create_task("canon-r2", {"x": 2}, "t-2", now_ts=1001)
        r2 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(r2.id, "network timeout", retry_delay_seconds=60, now_ts=2003)

        store.create_task(
            "canon-d1",
            {"x": 3},
            "t-3",
            max_attempts=1,
            now_ts=1002,
        )
        d1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        store.mark_retryable(d1.id, "invalid payload", retry_delay_seconds=60, now_ts=2005)

        groups = store.list_failure_groups(limit=10, offset=0)
        self.assertEqual(store.count_failure_groups(), 2)
        self.assertEqual(len(groups), 2)

        retry_group = next(
            item
            for item in groups
            if item["status"] == "retryable" and item["error"] == "network timeout"
        )
        dead_group = next(
            item
            for item in groups
            if item["status"] == "dead" and item["error"] == "invalid payload"
        )

        self.assertEqual(retry_group["count"], 2)
        self.assertEqual(dead_group["count"], 1)
        self.assertEqual(store.count_failure_groups(status="retryable"), 1)
        self.assertEqual(store.count_failure_groups(status="dead"), 1)

    def test_failure_groups_use_normalized_error_key(self):
        path = TMP_DIR / "tasks_failure_groups_normalized.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-r1", {"x": 1}, "t-1", now_ts=1000)
        r1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(
            r1.id,
            "upstream timeout for entry 123 url=https://example.com/a",
            retry_delay_seconds=60,
            now_ts=2001,
        )

        store.create_task("canon-r2", {"x": 2}, "t-2", now_ts=1001)
        r2 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(
            r2.id,
            "upstream timeout for entry 456 url=https://example.com/b",
            retry_delay_seconds=60,
            now_ts=2003,
        )

        expected_key = normalize_error_key(
            "upstream timeout for entry 999 url=https://example.com/c"
        )
        groups = store.list_failure_groups(status="retryable", error_key=expected_key)
        self.assertEqual(store.count_failure_groups(status="retryable", error_key=expected_key), 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["error_key"], expected_key)
        self.assertEqual(groups[0]["count"], 2)

    def test_requeue_task_moves_dead_to_pending(self):
        path = TMP_DIR / "tasks_requeue_single.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task(
            "canon-dead",
            {"x": 1},
            "t-1",
            max_attempts=1,
            now_ts=1000,
        )
        dead_task = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(dead_task.id, "invalid payload", retry_delay_seconds=30, now_ts=2001)

        requeued = store.requeue_task(dead_task.id, now_ts=2002)
        self.assertTrue(requeued)

        refreshed = store.get_task(dead_task.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, "pending")
        self.assertIsNone(refreshed.last_error)
        self.assertIsNone(refreshed.next_retry_at)
        self.assertIsNone(refreshed.leased_until)

    def test_requeue_tasks_batch_filters_by_status_and_error_key(self):
        path = TMP_DIR / "tasks_requeue_batch.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-r1", {"x": 1}, "t-1", now_ts=1000)
        r1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(r1.id, "network timeout", retry_delay_seconds=30, now_ts=2001)

        store.create_task("canon-r2", {"x": 2}, "t-2", now_ts=1001)
        r2 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(r2.id, "network timeout", retry_delay_seconds=30, now_ts=2003)

        store.create_task("canon-r3", {"x": 3}, "t-3", now_ts=1002)
        r3 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2004)[0]
        store.mark_retryable(r3.id, "rate limited", retry_delay_seconds=30, now_ts=2005)

        affected = store.requeue_tasks(
            status="retryable",
            limit=10,
            error_key="network timeout",
            now_ts=2010,
        )
        self.assertEqual(affected, 2)

        task_r1 = store.get_task(r1.id)
        task_r2 = store.get_task(r2.id)
        task_r3 = store.get_task(r3.id)
        self.assertEqual(task_r1.status, "pending")
        self.assertEqual(task_r2.status, "pending")
        self.assertEqual(task_r3.status, "retryable")

    def test_list_failed_tasks_supports_filters_and_payload_flag(self):
        path = TMP_DIR / "tasks_failed_list.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-r1", {"x": 1}, "t-1", now_ts=1000)
        r1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(r1.id, "network timeout #101", retry_delay_seconds=30, now_ts=2001)

        store.create_task(
            "canon-d1",
            {"x": 2},
            "t-2",
            max_attempts=1,
            now_ts=1001,
        )
        d1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(d1.id, "invalid payload", retry_delay_seconds=30, now_ts=2003)

        self.assertEqual(store.count_failed_tasks(), 2)
        self.assertEqual(store.count_failed_tasks(status="retryable"), 1)
        self.assertEqual(store.count_failed_tasks(status="dead"), 1)

        timeout_key = normalize_error_key("network timeout #999")
        self.assertEqual(
            store.count_failed_tasks(status="retryable", error_key=timeout_key),
            1,
        )

        tasks_without_payload = store.list_failed_tasks(
            status="retryable",
            error_key=timeout_key,
            limit=10,
            offset=0,
            include_payload=False,
        )
        self.assertEqual(len(tasks_without_payload), 1)
        self.assertEqual(tasks_without_payload[0].payload, {})
        self.assertEqual(tasks_without_payload[0].error_key, timeout_key)

        tasks_with_payload = store.list_failed_tasks(
            status="retryable",
            error_key=timeout_key,
            limit=10,
            offset=0,
            include_payload=True,
        )
        self.assertEqual(len(tasks_with_payload), 1)
        self.assertEqual(tasks_with_payload[0].payload, {"x": 1})

    def test_requeue_tasks_supports_status_none_for_failed_tasks(self):
        path = TMP_DIR / "tasks_requeue_status_none.db"
        store = TaskStoreSQLite(path=str(path))

        store.create_task("canon-r1", {"x": 1}, "t-1", now_ts=1000)
        r1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2000)[0]
        store.mark_retryable(r1.id, "network timeout", retry_delay_seconds=30, now_ts=2001)

        store.create_task(
            "canon-d1",
            {"x": 2},
            "t-2",
            max_attempts=1,
            now_ts=1001,
        )
        d1 = store.claim_tasks(limit=1, lease_seconds=10, now_ts=2002)[0]
        store.mark_retryable(d1.id, "invalid payload", retry_delay_seconds=30, now_ts=2003)

        affected = store.requeue_tasks(status=None, limit=10, now_ts=2010)
        self.assertEqual(affected, 2)
        self.assertEqual(store.get_task(r1.id).status, "pending")
        self.assertEqual(store.get_task(d1.id).status, "pending")

