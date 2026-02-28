import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from adapters.protocols import LLMClientProtocol
from common.logger import ensure_logger


@dataclass
class EntryState:
    attempts_used: int = 0
    max_attempts: int = 0
    created_at: float = field(default_factory=time.time)
    last_attempt_at: float = 0.0
    ttl_seconds: float = 0.0
    status: str = "normal"


class LLMRequestPool:
    def __init__(
        self,
        llm_gateway: LLMClientProtocol,
        max_concurrent: int,
        rpm_limit: Optional[int] = None,
        daily_limit: Optional[int] = None,
        capacity: Optional[int] = None,
    ):
        self._llm_gateway = llm_gateway
        self._semaphore = threading.Semaphore(max_concurrent or 1)
        self._rpm_limit = rpm_limit
        self._daily_limit = daily_limit
        self._lock = threading.Lock()
        self._window_start = time.time()
        self._window_count = 0
        self._day_start = self._current_day_start()
        self._day_count = 0
        self._queue = deque(maxlen=capacity or 0) if capacity and capacity > 0 else None
        self._states: Dict[str, EntryState] = {}
        self._states_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._total_calls = 0
        self._total_errors = 0
        self._total_rejected = 0

    def _current_day_start(self) -> float:
        now = time.time()
        return now - (now % 86400)

    def _acquire_rate_slot(self):
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

    def _before_entry(
        self,
        entry_key: str,
        expected_retries: int,
        ttl_seconds: float,
        logger: Any,
    ) -> Optional[str]:
        log = ensure_logger(logger)
        now = time.time()
        with self._states_lock:
            state = self._states.get(entry_key)
            if state is None:
                max_attempts = 1 + max(0, int(expected_retries))
                state = EntryState(
                    attempts_used=0,
                    max_attempts=max_attempts,
                    created_at=now,
                    last_attempt_at=0.0,
                    ttl_seconds=float(ttl_seconds) if ttl_seconds is not None else 0.0,
                    status="normal",
                )
                self._states[entry_key] = state
                if self._queue is not None:
                    dropped_key = None
                    if len(self._queue) == self._queue.maxlen:
                        dropped_key = self._queue.popleft()
                    self._queue.append(entry_key)
                    if dropped_key is not None:
                        dropped_state = self._states.get(dropped_key)
                        if dropped_state is not None:
                            dropped_state.status = "dropped"
                        log.warning(f"LLMRequestPool: entry_dropped entry_key={dropped_key}")
            else:
                if state.ttl_seconds > 0 and now - state.created_at > state.ttl_seconds:
                    state.status = "expired"
                    log.warning(
                        "LLMRequestPool: entry_expired "
                        f"entry_key={entry_key} attempts_used={state.attempts_used}"
                    )
                    return "expired"
                if state.max_attempts > 0 and state.attempts_used >= state.max_attempts:
                    state.status = "failed"
                    log.warning(
                        "LLMRequestPool: entry_max_attempts_exceeded "
                        f"entry_key={entry_key} attempts_used={state.attempts_used}"
                    )
                    return "max_attempts_exceeded"
            state.attempts_used += 1
            state.last_attempt_at = now
        return None

    def _on_failure(self, entry_key: str, logger: Any, error: Exception):
        with self._states_lock:
            state = self._states.get(entry_key)
            attempts = state.attempts_used if state is not None else 0
            status = state.status if state is not None else "unknown"
        log = ensure_logger(logger)
        log.error(
            "LLMRequestPool: entry_call_failed "
            f"entry_key={entry_key} attempts_used={attempts} "
            f"status={status} error={error}"
        )

    def call(
        self,
        prompt: str,
        request: str,
        *,
        logger: Any = None,
        entry_key: Optional[str] = None,
        expected_retries: Optional[int] = None,
        ttl_seconds: Optional[float] = None,
    ) -> Tuple[Optional[str], Optional[object]]:
        log = ensure_logger(logger)
        if (
            entry_key is not None
            and expected_retries is not None
            and ttl_seconds is not None
        ):
            reason = self._before_entry(
                entry_key, expected_retries, ttl_seconds, log
            )
            if reason is not None:
                with self._metrics_lock:
                    self._total_rejected += 1
                return None, reason
        self._semaphore.acquire()
        try:
            self._acquire_rate_slot()
            try:
                start = time.time()
                result = self._llm_gateway.get_result(prompt, request, log)
                duration_ms = int((time.time() - start) * 1000)
                with self._metrics_lock:
                    self._total_calls += 1
                log.debug(f"LLMRequestPool: call_success duration_ms={duration_ms}")
                return result, None
            except Exception as e:
                with self._metrics_lock:
                    self._total_calls += 1
                    self._total_errors += 1
                if entry_key is not None:
                    self._on_failure(entry_key, log, e)
                return None, e
        finally:
            self._semaphore.release()

    def get_result(
        self,
        prompt: str,
        request: str,
        logger: Any = None,
        **kwargs: Any,
    ) -> str:
        entry_key = kwargs.pop("entry_key", None)
        expected_retries = kwargs.pop("expected_retries", None)
        ttl_seconds = kwargs.pop("ttl_seconds", None)
        result, err = self.call(
            prompt,
            request,
            logger=logger,
            entry_key=entry_key,
            expected_retries=expected_retries,
            ttl_seconds=ttl_seconds,
        )
        if err is not None:
            if isinstance(err, Exception):
                raise err
            raise RuntimeError(f"LLMRequestPool error: {err}")
        return result or ""

    def get_state(self, entry_key: str) -> Optional[Dict[str, object]]:
        with self._states_lock:
            state = self._states.get(entry_key)
            if state is None:
                return None
            return {
                "attempts_used": state.attempts_used,
                "max_attempts": state.max_attempts,
                "created_at": state.created_at,
                "last_attempt_at": state.last_attempt_at,
                "ttl_seconds": state.ttl_seconds,
                "status": state.status,
            }

    def reset_entry(self, entry_key: str) -> None:
        with self._states_lock:
            if entry_key in self._states:
                del self._states[entry_key]
            if self._queue is not None and self._queue:
                self._queue = deque(
                    [k for k in self._queue if k != entry_key],
                    maxlen=self._queue.maxlen,
                )

    def clear_all(self) -> None:
        with self._states_lock:
            self._states.clear()
            if self._queue is not None:
                self._queue.clear()

    def get_metrics(self) -> Dict[str, int]:
        with self._metrics_lock:
            return {
                "total_calls": self._total_calls,
                "total_errors": self._total_errors,
                "total_rejected": self._total_rejected,
            }

    def get_failed_entries(self, limit: int = 100) -> Dict[str, Dict[str, object]]:
        with self._states_lock:
            items = [
                (
                    entry_key,
                    state,
                )
                for entry_key, state in self._states.items()
                if state.status in ("failed", "expired", "dropped")
            ]
            items.sort(key=lambda pair: pair[1].created_at, reverse=True)
            limited = items[: max(0, int(limit))]
            result: Dict[str, Dict[str, object]] = {}
            for entry_key, state in limited:
                result[entry_key] = {
                    "status": state.status,
                    "attempts_used": state.attempts_used,
                    "max_attempts": state.max_attempts,
                    "created_at": state.created_at,
                    "last_attempt_at": state.last_attempt_at,
                    "ttl_seconds": state.ttl_seconds,
                }
            return result
