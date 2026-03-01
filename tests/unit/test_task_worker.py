from pathlib import Path

from assert_utils import AssertMixin
from common.task_store import TASK_DEAD, TASK_DONE, TASK_RETRYABLE
from common.task_store_sqlite import TaskStoreSQLite
from core.task_worker import PermanentTaskError, TaskWorker


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_task_worker"


class CaptureLogger:
    def __init__(self):
        self.info_logs = []
        self.warning_logs = []
        self.error_logs = []

    def info(self, *args, **kwargs):
        self.info_logs.append(" ".join(str(i) for i in args))

    def warning(self, *args, **kwargs):
        self.warning_logs.append(" ".join(str(i) for i in args))

    def error(self, *args, **kwargs):
        self.error_logs.append(" ".join(str(i) for i in args))


class TestTaskWorker(AssertMixin):
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def _wait_status(self, store, task_id, expected, timeout_seconds=2.0):
        import time

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            row = store.get_task(task_id)
            if row is not None and row.status == expected:
                return row
            time.sleep(0.05)
        self.fail(f"task {task_id} did not reach status {expected}")

    def test_worker_marks_done_on_success(self):
        store = TaskStoreSQLite(path=str(TMP_DIR / "worker_done.db"))
        store.create_task("canon-1", {"entry": {"id": 1}, "feed": {}}, now_ts=1000)
        task = store.list_tasks()[0]
        logger = CaptureLogger()

        worker = TaskWorker(
            task_store=store,
            workers=1,
            claim_batch_size=1,
            poll_interval=0.05,
            logger=logger,
        )
        worker.start(lambda _: None)
        self._wait_status(store, task.id, TASK_DONE)
        worker.stop()
        done_logs = [line for line in logger.info_logs if "status=done" in line]
        self.assertTrue(done_logs)
        self.assertIn(f"task_id={task.id}", done_logs[-1])
        self.assertIn("canonical_id=canon-1", done_logs[-1])
        self.assertIn("attempts=1", done_logs[-1])
        self.assertIn("error=", done_logs[-1])

    def test_worker_marks_retryable_on_error(self):
        store = TaskStoreSQLite(path=str(TMP_DIR / "worker_retry.db"))
        store.create_task("canon-1", {"entry": {"id": 1}, "feed": {}}, now_ts=1000)
        task = store.list_tasks()[0]
        logger = CaptureLogger()

        worker = TaskWorker(
            task_store=store,
            workers=1,
            claim_batch_size=1,
            poll_interval=0.05,
            retry_delay_seconds=1,
            logger=logger,
        )
        worker.start(lambda _: (_ for _ in ()).throw(RuntimeError("temporary")))
        self._wait_status(store, task.id, TASK_RETRYABLE)
        worker.stop()
        retry_logs = [line for line in logger.warning_logs if "status=retryable" in line]
        self.assertTrue(retry_logs)
        self.assertIn(f"task_id={task.id}", retry_logs[-1])
        self.assertIn("canonical_id=canon-1", retry_logs[-1])
        self.assertIn("attempts=1", retry_logs[-1])
        self.assertIn("error=temporary", retry_logs[-1])

    def test_worker_marks_dead_on_permanent_error(self):
        store = TaskStoreSQLite(path=str(TMP_DIR / "worker_dead.db"))
        store.create_task("canon-1", {"entry": {"id": 1}, "feed": {}}, now_ts=1000)
        task = store.list_tasks()[0]
        logger = CaptureLogger()

        def _processor(_):
            raise PermanentTaskError("invalid payload")

        worker = TaskWorker(
            task_store=store,
            workers=1,
            claim_batch_size=1,
            poll_interval=0.05,
            logger=logger,
        )
        worker.start(_processor)
        self._wait_status(store, task.id, TASK_DEAD)
        worker.stop()
        dead_logs = [line for line in logger.warning_logs if "status=dead" in line]
        self.assertTrue(dead_logs)
        self.assertIn(f"task_id={task.id}", dead_logs[-1])
        self.assertIn("canonical_id=canon-1", dead_logs[-1])
        self.assertIn("attempts=1", dead_logs[-1])
        self.assertIn("error=invalid payload", dead_logs[-1])
