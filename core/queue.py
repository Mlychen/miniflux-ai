import logging
import queue
import threading
from typing import Any, List, Protocol


class QueueBackend(Protocol):

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
    def __init__(self, backend: QueueBackend, workers: int = 2):
        self._backend = backend
        self._workers = workers
        self._running = False
        self._threads: List[threading.Thread] = []
        self._logger = logging.getLogger("miniflux_ai")

    def start(self, processor_fn):
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
        if self._logger and hasattr(self._logger, "debug"):
            self._logger.debug(
                f"WebhookQueue.start: workers={self._workers} max_size={self._backend._max_size}"
            )

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()
        if self._logger and hasattr(self._logger, "debug"):
            self._logger.debug("WebhookQueue.stop: all workers joined")

    def _consumer_loop(self, processor_fn):
        while self._running:
            items = self._backend.dequeue(batch_size=10)
            if items and self._logger and hasattr(self._logger, "debug"):
                self._logger.debug(
                    f"WebhookQueue._consumer_loop: dequeued_batch_size={len(items)}"
                )
            for item in items:
                try:
                    processor_fn(item)
                except Exception as e:
                    if self._logger:
                        self._logger.error(f"Error processing webhook item: {e}")

    def enqueue(self, item: Any) -> bool:
        success = self._backend.enqueue(item)
        if self._logger and hasattr(self._logger, "debug"):
            size = self._backend.size()
            self._logger.debug(
                f"WebhookQueue.enqueue: success={success} queue_size={size}"
            )
        return success

    def size(self) -> int:
        return self._backend.size()

    @property
    def is_full(self) -> bool:
        return self.size() >= self._backend._max_size
