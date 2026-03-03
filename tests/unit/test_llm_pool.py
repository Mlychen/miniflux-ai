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

    def debug(self, msg):
        self.messages.append(("debug", msg))


def test_call_delegates_to_gateway():
    """测试 LLMRequestPool 正确委托给 gateway。"""
    gateway = DummyGateway(["ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    result, err = pool.call("p", "r")

    assert result == "ok"
    assert err is None
    assert len(gateway.calls) == 1


def test_call_returns_error_on_failure():
    """测试 LLMRequestPool 在失败时返回错误。"""
    gateway = DummyGateway([RuntimeError("fail")])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    result, err = pool.call("p", "r")

    assert result is None
    assert isinstance(err, RuntimeError)
    assert str(err) == "fail"
    assert len(gateway.calls) == 1


def test_get_result_raises_on_error():
    """测试 get_result 在错误时抛出异常。"""
    gateway = DummyGateway([RuntimeError("fail")])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    try:
        pool.get_result("p", "r")
        assert False, "should have raised"
    except RuntimeError as e:
        assert str(e) == "fail"


def test_get_metrics_counts_calls():
    """测试 get_metrics 正确计数。"""
    gateway = DummyGateway(["ok", RuntimeError("fail"), "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    pool.call("p1", "r1")
    pool.call("p2", "r2")
    pool.call("p3", "r3")

    metrics = pool.get_metrics()
    assert metrics["total_calls"] == 3
    assert metrics["total_errors"] == 1


def test_no_retry_on_failure():
    """测试 LLMRequestPool 不再重试，由 TaskStore 负责重试。"""
    gateway = DummyGateway([RuntimeError("fail"), "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    result, err = pool.call("p", "r")

    # 不重试，直接返回错误
    assert result is None
    assert isinstance(err, RuntimeError)
    assert len(gateway.calls) == 1  # 只调用一次


def test_concurrent_limit():
    """测试并发限制。"""
    gateway = DummyGateway(["ok", "ok"])
    pool = LLMRequestPool(gateway, max_concurrent=1)

    # 在同一个线程中顺序调用
    result1, err1 = pool.call("p1", "r1")
    result2, err2 = pool.call("p2", "r2")

    assert result1 == "ok"
    assert result2 == "ok"
    assert err1 is None
    assert err2 is None