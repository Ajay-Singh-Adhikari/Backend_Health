import pytest

from backend_health.retry import retry_with_backoff


def test_succeeds_first_try_no_sleep():
    sleeps = []
    assert retry_with_backoff(lambda: 42, sleep=sleeps.append) == 42
    assert sleeps == []


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    sleeps = []
    result = retry_with_backoff(flaky, attempts=3, base_delay_seconds=1.0, sleep=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]  # exponential backoff between the 2 failed attempts


def test_raises_last_exception_after_exhausting_attempts():
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        retry_with_backoff(always_fails, attempts=3, sleep=lambda _: None)


def test_attempts_one_disables_retry():
    calls = {"n": 0}

    def fails_once():
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry_with_backoff(fails_once, attempts=1, sleep=lambda _: None)
    assert calls["n"] == 1


def test_invalid_attempts_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        retry_with_backoff(lambda: None, attempts=0)
