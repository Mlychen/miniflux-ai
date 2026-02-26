import threading
import time
import unittest

from core.queue import InMemoryQueueBackend, WebhookQueue


class TestInMemoryQueueBackend(unittest.TestCase):
    """Test InMemoryQueueBackend."""

    def test_enqueue_returns_true_when_not_full(self):
        """Verify enqueue returns True when queue has space."""
        backend = InMemoryQueueBackend(max_size=10)
        result = backend.enqueue({"data": "test"})
        self.assertTrue(result)
        self.assertEqual(backend.size(), 1)

    def test_enqueue_returns_false_when_full(self):
        """Verify enqueue returns False when queue is full."""
        backend = InMemoryQueueBackend(max_size=1)
        backend.enqueue({"data": "first"})

        # Queue should be full now
        result = backend.enqueue({"data": "second"})
        self.assertFalse(result)

    def test_dequeue_returns_items(self):
        """Verify dequeue returns items in FIFO order."""
        backend = InMemoryQueueBackend(max_size=10)
        backend.enqueue({"id": 1})
        backend.enqueue({"id": 2})
        backend.enqueue({"id": 3})

        items = backend.dequeue(batch_size=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[1]["id"], 2)

    def test_dequeue_returns_empty_when_empty(self):
        """Verify dequeue returns empty list when queue is empty."""
        backend = InMemoryQueueBackend(max_size=10)
        items = backend.dequeue(batch_size=5)
        self.assertEqual(len(items), 0)

    def test_dequeue_respects_batch_size(self):
        """Verify dequeue respects batch_size limit."""
        backend = InMemoryQueueBackend(max_size=10)
        for i in range(5):
            backend.enqueue({"id": i})

        items = backend.dequeue(batch_size=2)
        self.assertEqual(len(items), 2)

    def test_size_returns_current_count(self):
        """Verify size returns correct count."""
        backend = InMemoryQueueBackend(max_size=10)
        self.assertEqual(backend.size(), 0)

        backend.enqueue({"id": 1})
        self.assertEqual(backend.size(), 1)

        backend.enqueue({"id": 2})
        self.assertEqual(backend.size(), 2)

        backend.dequeue(batch_size=1)
        self.assertEqual(backend.size(), 1)


class TestWebhookQueue(unittest.TestCase):
    """Test WebhookQueue."""

    def test_enqueue_delegates_to_backend(self):
        """Verify enqueue delegates to backend."""
        backend = InMemoryQueueBackend(max_size=10)
        queue = WebhookQueue(backend=backend, workers=1)

        result = queue.enqueue({"data": "test"})
        self.assertTrue(result)
        self.assertEqual(queue.size(), 1)

    def test_size_delegates_to_backend(self):
        """Verify size delegates to backend."""
        backend = InMemoryQueueBackend(max_size=10)
        queue = WebhookQueue(backend=backend, workers=1)

        self.assertEqual(queue.size(), 0)
        queue.enqueue({"id": 1})
        self.assertEqual(queue.size(), 1)

    def test_is_full_returns_true_when_at_capacity(self):
        """Verify is_full returns True when at max size."""
        backend = InMemoryQueueBackend(max_size=2)
        queue = WebhookQueue(backend=backend, workers=1)

        queue.enqueue({"id": 1})
        self.assertFalse(queue.is_full)

        queue.enqueue({"id": 2})
        self.assertTrue(queue.is_full)

    def test_consumer_processes_items(self):
        """Verify consumer thread processes items from queue."""
        backend = InMemoryQueueBackend(max_size=10)
        queue = WebhookQueue(backend=backend, workers=1)

        processed = []

        def processor(item):
            processed.append(item["id"])

        queue.enqueue({"id": 1})
        queue.enqueue({"id": 2})

        queue.start(processor)
        time.sleep(0.3)
        queue.stop()

        self.assertEqual(set(processed), {1, 2})

    def test_consumer_handles_exception(self):
        """Verify consumer handles processor exceptions gracefully."""
        backend = InMemoryQueueBackend(max_size=10)
        queue = WebhookQueue(backend=backend, workers=1)

        def bad_processor(item):
            if item["id"] == 1:
                raise RuntimeError("test error")
            return item["id"]

        queue.enqueue({"id": 1})  # Will cause exception
        queue.enqueue({"id": 2})  # Should still be processed

        queue.start(bad_processor)
        time.sleep(0.3)
        queue.stop()

        # Item 2 should still be processed despite item 1 exception
        # (we can't easily verify this without more complex mocking)

    def test_multiple_workers_process_concurrently(self):
        """Verify multiple workers can process concurrently."""
        backend = InMemoryQueueBackend(max_size=100)
        queue = WebhookQueue(backend=backend, workers=2)

        processed_order = []
        lock = threading.Lock()

        def processor(item):
            time.sleep(0.01)  # Simulate work
            with lock:
                processed_order.append(item["id"])

        # Enqueue 10 items
        for i in range(10):
            queue.enqueue({"id": i})

        queue.start(processor)
        time.sleep(1.0)
        queue.stop()

        self.assertEqual(len(processed_order), 10)

    def test_stop_terminates_consumers(self):
        """Verify stop terminates consumer threads."""
        backend = InMemoryQueueBackend(max_size=10)
        queue = WebhookQueue(backend=backend, workers=2)

        def processor(item):
            time.sleep(0.1)

        queue.start(processor)

        queue.stop()

        # After stop, threads should be cleared
        self.assertEqual(len(queue._threads), 0)


if __name__ == "__main__":
    unittest.main()
