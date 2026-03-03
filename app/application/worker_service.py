import threading
from typing import Callable, List


class PermanentTaskError(Exception):
    """Permanent task failure that should not be retried."""


class TaskWorker:
    def __init__(
        self,
        task_store,
        workers: int = 2,
        claim_batch_size: int = 20,
        lease_seconds: int = 60,
        poll_interval: float = 1.0,
        base_retry_delay_seconds: int = 30,
        logger=None,
    ):
        self._task_store = task_store
        self._workers = max(1, int(workers))
        self._claim_batch_size = max(1, int(claim_batch_size))
        self._lease_seconds = max(1, int(lease_seconds))
        self._poll_interval = max(0.05, float(poll_interval))
        self._base_retry_delay_seconds = max(0, int(base_retry_delay_seconds))
        self._logger = logger
        self._running = False
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()

    def _log(self, level: str, message: str) -> None:
        if not self._logger:
            return
        fn = getattr(self._logger, level, None)
        if callable(fn):
            fn(message)
            return
        fallback = getattr(self._logger, "info", None)
        if callable(fallback):
            fallback(message)

    def _task_log_line(self, task, status: str, error: str = "") -> str:
        task_id = getattr(task, "id", "")
        canonical_id = getattr(task, "canonical_id", "")
        attempts = getattr(task, "attempts", "")
        return (
            "TaskWorker.task_result "
            f"task_id={task_id} canonical_id={canonical_id} attempts={attempts} "
            f"status={status} error={str(error or '')}"
        )

    def start(self, processor_fn: Callable):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        for i in range(self._workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(processor_fn,),
                name=f"task-worker-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        if self._logger and hasattr(self._logger, "info"):
            self._logger.info(
                f"TaskWorker.start: workers={self._workers} claim_batch_size={self._claim_batch_size}"
            )

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()
        if self._logger and hasattr(self._logger, "info"):
            self._logger.info("TaskWorker.stop: all workers joined")

    def _worker_loop(self, processor_fn: Callable):
        current_poll_interval = self._poll_interval
        # Cap max poll interval at 10s or 10x the base interval
        max_poll_interval = max(10.0, self._poll_interval * 10)

        while self._running and not self._stop_event.is_set():
            try:
                tasks = self._task_store.claim_tasks(
                    limit=self._claim_batch_size,
                    lease_seconds=self._lease_seconds,
                )
            except Exception as e:
                self._log("error", f"TaskWorker.claim_tasks error={e}")
                self._stop_event.wait(self._poll_interval)
                continue

            if not tasks:
                if hasattr(self._task_store, "wait_for_new_task"):
                    # Wait for signal or timeout (adaptive backoff)
                    self._task_store.wait_for_new_task(timeout=current_poll_interval)
                else:
                    self._stop_event.wait(current_poll_interval)
                
                # Exponential backoff: increase wait time when idle
                current_poll_interval = min(current_poll_interval * 1.5, max_poll_interval)
                continue

            # Reset poll interval immediately when tasks are found
            current_poll_interval = self._poll_interval

            for task in tasks:
                try:
                    processor_fn(task)
                except PermanentTaskError as e:
                    try:
                        self._task_store.mark_dead(task.id, str(e))
                        self._log("warning", self._task_log_line(task, status="dead", error=str(e)))
                    except Exception as mark_err:
                        self._log(
                            "error",
                            self._task_log_line(
                                task, status="dead", error=f"mark_dead_failed:{mark_err}"
                            ),
                        )
                    continue
                except Exception as e:
                    # 动态计算延迟：delay = base_delay * attempts
                    retry_delay = self._base_retry_delay_seconds * max(1, getattr(task, "attempts", 1))
                    try:
                        self._task_store.mark_retryable(
                            task.id,
                            str(e),
                            retry_delay_seconds=retry_delay,
                        )
                        self._log(
                            "warning",
                            self._task_log_line(task, status="retryable", error=str(e)),
                        )
                    except Exception as mark_err:
                        self._log(
                            "error",
                            self._task_log_line(
                                task,
                                status="retryable",
                                error=f"mark_retryable_failed:{mark_err}",
                            ),
                        )
                    continue

                try:
                    self._task_store.mark_done(task.id)
                    self._log("info", self._task_log_line(task, status="done"))
                except Exception as e:
                    self._log(
                        "error",
                        self._task_log_line(task, status="done", error=f"mark_done_failed:{e}"),
                    )
