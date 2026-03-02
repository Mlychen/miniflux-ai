import time

import psutil

from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.application.worker_service import TaskWorker


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
    worker._worker_loop(lambda t: None)
    assert len(timeouts) >= 3
    expected_1 = timeouts[0] * 1.5
    expected_2 = expected_1 * 1.5
    assert abs(timeouts[1] - expected_1) < 1e-6
    assert abs(timeouts[2] - expected_2) < 1e-6


def test_task_worker_idle_cpu_usage(tmp_path):
    store = TaskStoreSQLite(path=str(tmp_path / "tasks_idle_cpu.db"))
    worker = TaskWorker(store, workers=1, poll_interval=0.1)
    worker.start(lambda t: None)
    try:
        process = psutil.Process()
        process.cpu_percent(interval=None)
        samples = []
        end_time = time.time() + 2.0
        while time.time() < end_time:
            samples.append(process.cpu_percent(interval=0.2))
        avg_cpu = sum(samples) / len(samples) if samples else 0.0
        assert avg_cpu < 20.0
    finally:
        worker.stop()
