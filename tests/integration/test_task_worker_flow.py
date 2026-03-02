import time

from app.domain.task_store import TASK_DONE, TASK_RETRYABLE
from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.application.worker_service import TaskWorker


def wait_for_status(task_store, task_id, status, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = task_store.get_task(task_id)
        if task and task.status == status:
            return task
        time.sleep(0.05)
    return task_store.get_task(task_id)


def test_task_worker_marks_done(tmp_path):
    store = TaskStoreSQLite(path=str(tmp_path / "tasks_done.db"))
    store.create_task("canon-1", {"entry_id": 1}, "trace-1", max_attempts=3)
    task = store.list_tasks()[0]
    worker = TaskWorker(store, workers=1, poll_interval=0.05, retry_delay_seconds=1)
    worker.start(lambda t: None)
    try:
        done_task = wait_for_status(store, task.id, TASK_DONE)
        assert done_task is not None
        assert done_task.status == TASK_DONE
    finally:
        worker.stop()


def test_task_worker_marks_retryable(tmp_path):
    store = TaskStoreSQLite(path=str(tmp_path / "tasks_retry.db"))
    store.create_task("canon-2", {"entry_id": 2}, "trace-2", max_attempts=3)
    task = store.list_tasks()[0]

    def failing(_task):
        raise RuntimeError("boom")

    worker = TaskWorker(store, workers=1, poll_interval=0.05, retry_delay_seconds=1)
    worker.start(failing)
    try:
        retry_task = wait_for_status(store, task.id, TASK_RETRYABLE)
        assert retry_task is not None
        assert retry_task.status == TASK_RETRYABLE
        assert retry_task.attempts >= 1
        assert retry_task.next_retry_at is not None
    finally:
        worker.stop()
