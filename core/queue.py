import queue
import threading
from typing import Any, List, Protocol


class QueueBackend(Protocol):
    """Protocol for queue backends (easily replaceable with Redis, RabbitMQ, etc)."""

    def enqueue(self, item: Any) -> bool:
        """Add item to queue. Returns True if successful, False if queue is full."""
        ...

    def dequeue(self, batch_size: int) -> List[Any]:
        """Remove and return up to batch_size items from queue."""
        ...

    def size(self) -> int:
        """Return current queue size."""
        ...


class InMemoryQueueBackend:
    """In-memory queue backend using queue.Queue with thread safety."""

    def __init__(self, max_size: int = 1000):
        self._queue = queue.Queue(maxsize=max_size)
        self._max_size = max_size

    def enqueue(self, item: Any) -> bool:
        try:
            self._queue.put(item, block=False)
            return True
        except queue.Full:
            return False

    def dequeue(self, batch_size: int) -> List[Any]:
        items = []
        for _ in range(batch_size):
            try:
                item = self._queue.get(block=False)
                items.append(item)
            except queue.Empty:
                break
        return items

    def size(self) -> int:
        return self._queue.qsize()


class WebhookQueue:
    """Webhook queue with background consumer."""

    def __init__(self, backend: QueueBackend, workers: int = 2):
        self._backend = backend
        self._workers = workers
        self._running = False
        self._threads: List[threading.Thread] = []

    def start(self, processor_fn):
        """Start background consumer threads."""
        self._running = True
        for i in range(self._workers):
            t = threading.Thread(
                target=self._consumer_loop,
                args=(processor_fn,),
                name=f"webhook-consumer-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self):
        """Stop background consumer threads."""
        self._running = False
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()

    def _consumer_loop(self, processor_fn):
        """Background consumer loop."""
        while self._running:
            items = self._backend.dequeue(batch_size=10)
            for item in items:
                try:
                    processor_fn(item)
                except Exception as e:
                    # Log error but don't crash consumer
                    import logging

                    logging.error(f"Error processing webhook item: {e}")

    def enqueue(self, item: Any) -> bool:
        """Add item to queue."""
        return self._backend.enqueue(item)

    def size(self) -> int:
        """Return current queue size."""
        return self._backend.size()

    @property
    def is_full(self) -> bool:
        """Check if queue is at capacity."""
        return self.size() >= self._backend._max_size
