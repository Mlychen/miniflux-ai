import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from app.infrastructure.protocols import LLMClientProtocol
from app.observability.trace import ensure_logger


class LLMRequestPool:
    """真正的线程池实现：内部工作线程从队列消费请求。"""

    def __init__(
        self,
        llm_gateway: LLMClientProtocol,
        max_concurrent: int,
        rpm_limit: Optional[int] = None,
        daily_limit: Optional[int] = None,
        capacity: Optional[int] = None,
    ):
        self._llm_gateway = llm_gateway
        self._max_concurrent = max_concurrent or 1
        self._capacity = capacity or 100
        self._queue: queue.Queue = queue.Queue(maxsize=self._capacity)
        self._workers: list = []
        self._running = True
        self._rpm_limit = rpm_limit
        self._daily_limit = daily_limit
        self._lock = threading.Lock()
        self._window_start = time.time()
        self._window_count = 0
        self._day_start = self._current_day_start()
        self._day_count = 0
        self._metrics_lock = threading.Lock()
        self._total_calls = 0
        self._total_errors = 0
        self._start_workers()

    def _current_day_start(self) -> float:
        now = time.time()
        return now - (now % 86400)

    def _start_workers(self):
        """启动内部工作线程。"""
        for i in range(self._max_concurrent):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self):
        """工作线程主循环：从队列获取请求并执行。"""
        while self._running:
            try:
                prompt, request, callback, logger = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._acquire_rate_slot()
                start = time.time()
                result = self._llm_gateway.get_result(prompt, request, logger)
                duration_ms = int((time.time() - start) * 1000)
                with self._metrics_lock:
                    self._total_calls += 1
                if logger:
                    logger.debug(f"LLMRequestPool: call_success duration_ms={duration_ms}")
                callback(result, None)
            except Exception as e:
                with self._metrics_lock:
                    self._total_calls += 1
                    self._total_errors += 1
                if logger:
                    logger.error(f"LLMRequestPool: call_failed error={e}")
                callback(None, e)

    def _acquire_rate_slot(self):
        """获取限流槽位，必要时等待。"""
        if self._rpm_limit is None and self._daily_limit is None:
            return
        while True:
            now = time.time()
            with self._lock:
                if self._rpm_limit is not None and now - self._window_start >= 60:
                    self._window_start = now
                    self._window_count = 0
                if self._daily_limit is not None and now - self._day_start >= 86400:
                    self._day_start = self._current_day_start()
                    self._day_count = 0
                window_ok = (
                    self._rpm_limit is None or self._window_count < self._rpm_limit
                )
                day_ok = (
                    self._daily_limit is None or self._day_count < self._daily_limit
                )
                if window_ok and day_ok:
                    self._window_count += 1
                    self._day_count += 1
                    return
                sleep_for = 1.0
                if self._rpm_limit is not None:
                    remaining = 60 - (now - self._window_start)
                    if remaining > 0:
                        sleep_for = max(sleep_for, remaining)
                if self._daily_limit is not None:
                    remaining_day = 86400 - (now - self._day_start)
                    if remaining_day > 0:
                        sleep_for = max(sleep_for, remaining_day)
            time.sleep(min(sleep_for, 60))

    def submit(
        self,
        prompt: str,
        request: str,
        callback: Callable[[Optional[str], Optional[Exception]], None],
        logger: Any = None,
    ):
        """提交请求到队列，满时抛出 queue.Full 异常。"""
        self._queue.put((prompt, request, callback, logger), block=False)

    def call(
        self,
        prompt: str,
        request: str,
        *,
        logger: Any = None,
        **kwargs,
    ) -> Tuple[Optional[str], Optional[object]]:
        """同步调用，阻塞等待结果。"""
        result = [None]
        error = [None]
        event = threading.Event()

        def cb(r, e):
            result[0] = r
            error[0] = e
            event.set()

        self.submit(prompt, request, cb, logger)
        event.wait()
        return result[0], error[0]

    def get_result(
        self,
        prompt: str,
        request: str,
        logger: Any = None,
        **kwargs: Any,
    ) -> str:
        result, err = self.call(prompt, request, logger=logger)
        if err is not None:
            if isinstance(err, Exception):
                raise err
            raise RuntimeError(f"LLMRequestPool error: {err}")
        return result or ""

    def get_metrics(self) -> Dict[str, int]:
        with self._metrics_lock:
            return {
                "total_calls": self._total_calls,
                "total_errors": self._total_errors,
            }
