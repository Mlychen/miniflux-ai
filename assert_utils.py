class AssertMixin:
    def _msg(self, msg, default):
        return msg or default

    def assertEqual(self, first, second, msg=None):
        assert first == second, self._msg(msg, f"{first} != {second}")

    def assertNotEqual(self, first, second, msg=None):
        assert first != second, self._msg(msg, f"{first} == {second}")

    def assertTrue(self, expr, msg=None):
        assert expr, self._msg(msg, f"{expr} is not True")

    def assertFalse(self, expr, msg=None):
        assert not expr, self._msg(msg, f"{expr} is not False")

    def assertIsNone(self, expr, msg=None):
        assert expr is None, self._msg(msg, f"{expr} is not None")

    def assertIsNotNone(self, expr, msg=None):
        assert expr is not None, self._msg(msg, "is None")

    def assertIs(self, first, second, msg=None):
        assert first is second, self._msg(msg, f"{first} is not {second}")

    def assertIsNot(self, first, second, msg=None):
        assert first is not second, self._msg(msg, f"{first} is {second}")

    def assertIn(self, member, container, msg=None):
        assert member in container, self._msg(msg, f"{member} not in container")

    def assertNotIn(self, member, container, msg=None):
        assert member not in container, self._msg(msg, f"{member} in container")

    def assertGreater(self, first, second, msg=None):
        assert first > second, self._msg(msg, f"{first} <= {second}")

    def assertGreaterEqual(self, first, second, msg=None):
        assert first >= second, self._msg(msg, f"{first} < {second}")

    def assertLess(self, first, second, msg=None):
        assert first < second, self._msg(msg, f"{first} >= {second}")

    def assertLessEqual(self, first, second, msg=None):
        assert first <= second, self._msg(msg, f"{first} > {second}")

    def assertIsInstance(self, obj, cls, msg=None):
        assert isinstance(obj, cls), self._msg(msg, f"{obj} is not {cls}")

    def fail(self, msg=None):
        raise AssertionError(msg or "failed")
