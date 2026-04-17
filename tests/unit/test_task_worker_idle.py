import time

from app.application.worker_service import TaskWorker
from app.infrastructure.task_store_sqlite import TaskStoreSQLite


def test_task_worker_idle_backoff_increases(tmp_path, monkeypatch):
    store = TaskStoreSQLite(path=str(tmp_path / "tasks_idle.db"))
    worker = TaskWorker(store, workers=1, poll_interval=0.1)
    timeouts = []

    def wait_for_new_task(timeout=1.0):
        timeouts.append(timeout)
        if len(timeouts) >= 3:
            worker._running = False
            worker._stop_event.set()
        time.sleep(0.01)

    monkeypatch.setattr(store, "wait_for_new_task", wait_for_new_task)
    worker._running = True
    worker._stop_event.clear()

    worker._worker_loop(lambda task: None)

    assert len(timeouts) >= 3
    assert abs(timeouts[1] - (timeouts[0] * 1.5)) < 1e-6
    assert abs(timeouts[2] - (timeouts[1] * 1.5)) < 1e-6


def test_task_worker_idle_claim_frequency_stays_bounded(tmp_path):
    store = TaskStoreSQLite(path=str(tmp_path / "tasks_idle_frequency.db"))
    worker = TaskWorker(store, workers=1, poll_interval=0.1)
    claim_count = 0

    def claim_tasks(limit, lease_seconds):
        nonlocal claim_count
        claim_count += 1
        return []

    store.claim_tasks = claim_tasks
    worker.start(lambda task: None)
    try:
        time.sleep(2.0)
        assert claim_count <= 8
    finally:
        worker.stop()
