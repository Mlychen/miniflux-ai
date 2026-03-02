from types import SimpleNamespace

from app.application.llm_pool import LLMRequestPool


class DummyGateway:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = []

    def get_result(self, prompt, request, logger=None):
        self.calls.append((prompt, request))
        if not self._outputs:
            raise RuntimeError("no more outputs")
        result = self._outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class DummyLogger:
    def __init__(self):
        self.messages = []

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


def test_call_without_entry_key_delegates_to_gateway():
    gateway = DummyGateway(["ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    result, err = pool.call("p", "r")

    assert result == "ok"
    assert err is None
    assert len(gateway.calls) == 1


def test_entry_max_attempts_exceeded():
    gateway = DummyGateway(["ok", "ok", "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)
    logger = DummyLogger()

    for _ in range(3):
        result, err = pool.call(
            "p",
            "r",
            entry_key="k",
            expected_retries=2,
            ttl_seconds=100,
            logger=logger,
        )
        assert result == "ok"
        assert err is None

    result, err = pool.call(
        "p",
        "r",
        entry_key="k",
        expected_retries=2,
        ttl_seconds=100,
        logger=logger,
    )

    assert result is None
    assert err == "max_attempts_exceeded"
    assert len(gateway.calls) == 3


def test_entry_ttl_expired():
    fake_time = SimpleNamespace(value=1000.0)

    def fake_time_fn():
        return fake_time.value

    import app.application.llm_pool as llm_pool_mod

    original_time = llm_pool_mod.time.time
    llm_pool_mod.time.time = fake_time_fn
    try:
        gateway = DummyGateway(["ok"])
        pool = LLMRequestPool(gateway, max_concurrent=1)
        logger = DummyLogger()

        result, err = pool.call(
            "p",
            "r",
            entry_key="k",
            expected_retries=1,
            ttl_seconds=5,
            logger=logger,
        )
        assert result == "ok"
        assert err is None

        fake_time.value += 10
        result, err = pool.call(
            "p",
            "r",
            entry_key="k",
            expected_retries=1,
            ttl_seconds=5,
            logger=logger,
        )
        assert result is None
        assert err == "expired"
    finally:
        llm_pool_mod.time.time = original_time


def test_capacity_drops_old_entries():
    gateway = DummyGateway(["ok", "ok", "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1, capacity=2)
    logger = DummyLogger()

    for key in ["k1", "k2", "k3"]:
        result, err = pool.call(
            "p",
            "r",
            entry_key=key,
            expected_retries=1,
            ttl_seconds=100,
            logger=logger,
        )
        assert result == "ok"
        assert err is None

    state_k1 = pool.get_state("k1")
    state_k2 = pool.get_state("k2")
    state_k3 = pool.get_state("k3")

    assert state_k1 is not None
    assert state_k1["status"] == "dropped"
    assert state_k2["status"] == "normal"
    assert state_k3["status"] == "normal"


def test_call_retries_within_single_request():
    gateway = DummyGateway([RuntimeError("fail-1"), RuntimeError("fail-2"), "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    result, err = pool.call(
        "p",
        "r",
        entry_key="retry-key",
        expected_retries=2,
        ttl_seconds=100,
    )

    assert result == "ok"
    assert err is None
    assert len(gateway.calls) == 3
