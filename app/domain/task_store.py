from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_RETRYABLE = "retryable"
TASK_DEAD = "dead"
TASK_DONE = "done"

TASK_STATUSES = {
    TASK_PENDING,
    TASK_RUNNING,
    TASK_RETRYABLE,
    TASK_DEAD,
    TASK_DONE,
}


@dataclass(frozen=True)
class TaskRecord:
    id: int
    canonical_id: str
    payload: Dict[str, Any]
    trace_id: str
    status: str
    attempts: int
    max_attempts: int
    next_retry_at: Optional[int]
    leased_until: Optional[int]
    last_error: Optional[str]
    error_key: str
    created_at: int
    updated_at: int


class TaskStore(Protocol):
    def create_task(
        self,
        canonical_id: str,
        payload: Dict[str, Any],
        trace_id: str = "",
        max_attempts: int = 5,
        now_ts: Optional[int] = None,
    ) -> bool:
        """Create task if canonical_id does not exist. Returns True when inserted."""
        ...

    def claim_tasks(
        self,
        limit: int,
        lease_seconds: int = 30,
        now_ts: Optional[int] = None,
    ) -> List[TaskRecord]:
        """Atomically claim runnable tasks and return them in running state."""
        ...

    def mark_done(self, task_id: int, now_ts: Optional[int] = None) -> None:
        """Mark a task as done."""
        ...

    def mark_retryable(
        self,
        task_id: int,
        error: str,
        retry_delay_seconds: int = 30,
        now_ts: Optional[int] = None,
    ) -> None:
        """Mark a task as retryable, or dead when attempts exceed max_attempts."""
        ...

    def mark_dead(self, task_id: int, error: str, now_ts: Optional[int] = None) -> None:
        """Mark a task as dead."""
        ...

    def get_task(self, task_id: int) -> Optional[TaskRecord]:
        """Fetch task by id."""
        ...

    def get_task_by_canonical_id(self, canonical_id: str) -> Optional[TaskRecord]:
        """Fetch task by canonical_id."""
        ...

    def list_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_payload: bool = True,
    ) -> List[TaskRecord]:
        """List tasks by optional status."""
        ...

    def count_tasks(self, status: Optional[str] = None) -> int:
        """Count tasks by optional status."""
        ...

    def count_tasks_by_status(self) -> Dict[str, int]:
        """Count tasks grouped by status."""
        ...

    def get_metrics(
        self,
        now_ts: Optional[int] = None,
        throughput_window_seconds: int = 300,
    ) -> Dict[str, Any]:
        """Return aggregated task metrics for observability."""
        ...

    def count_failure_groups(
        self, status: Optional[str] = None, error_key: Optional[str] = None
    ) -> int:
        """Count grouped failures for retryable/dead tasks."""
        ...

    def list_failure_groups(
        self,
        status: Optional[str] = None,
        error_key: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List grouped failures for retryable/dead tasks."""
        ...

    def requeue_task(self, task_id: int, now_ts: Optional[int] = None) -> bool:
        """Requeue a single task to pending state."""
        ...

    def requeue_tasks(
        self,
        status: Optional[str] = TASK_DEAD,
        limit: int = 100,
        error_key: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        """Requeue tasks in batch and return affected count."""
        ...

    def count_failed_tasks(
        self, status: Optional[str] = None, error_key: Optional[str] = None
    ) -> int:
        """Count failed tasks (retryable/dead) with optional filters."""
        ...

    def list_failed_tasks(
        self,
        status: Optional[str] = None,
        error_key: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_payload: bool = False,
    ) -> List[TaskRecord]:
        """List failed tasks (retryable/dead) with optional filters."""
        ...
