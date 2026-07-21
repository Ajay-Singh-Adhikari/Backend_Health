import logging

from backend_health.alerts import LoggingAlerter, WebhookAlerter, get_alerter


def test_logging_alerter_logs_error(caplog):
    with caplog.at_level(logging.ERROR):
        LoggingAlerter().notify("tenant-a", 3, "boom")
    assert "tenant-a" in caplog.text
    assert "3 consecutive" in caplog.text


def test_get_alerter_defaults_to_logging():
    assert isinstance(get_alerter(), LoggingAlerter)
    assert isinstance(get_alerter(webhook_url=None), LoggingAlerter)


def test_get_alerter_uses_explicit_webhook_url():
    alerter = get_alerter(webhook_url="https://hooks.example.com/x")
    assert isinstance(alerter, WebhookAlerter)
    assert alerter.url == "https://hooks.example.com/x"


def test_get_alerter_reads_env_var(monkeypatch):
    monkeypatch.setenv("BACKEND_HEALTH_ALERT_WEBHOOK", "https://hooks.example.com/env")
    alerter = get_alerter()
    assert isinstance(alerter, WebhookAlerter)
    assert alerter.url == "https://hooks.example.com/env"


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeSession:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return _FakeResponse(self.status_code)


def test_webhook_alerter_posts_payload():
    session = _FakeSession()
    alerter = WebhookAlerter("https://hooks.example.com/x", session=session)
    alerter.notify("tenant-a", 3, "boom")
    assert len(session.calls) == 1
    url, payload = session.calls[0]
    assert url == "https://hooks.example.com/x"
    assert "tenant-a" in payload["text"]


def test_webhook_alerter_does_not_raise_on_error_status(caplog):
    session = _FakeSession(status_code=500)
    alerter = WebhookAlerter("https://hooks.example.com/x", session=session)
    with caplog.at_level(logging.ERROR):
        alerter.notify("tenant-a", 3, "boom")  # must not raise
    assert "500" in caplog.text


def test_webhook_alerter_does_not_raise_on_request_exception(caplog):
    import requests

    class RaisingSession:
        def post(self, *_, **__):
            raise requests.ConnectionError("network down")

    alerter = WebhookAlerter("https://hooks.example.com/x", session=RaisingSession())
    with caplog.at_level(logging.ERROR):
        alerter.notify("tenant-a", 3, "boom")  # must not raise
    assert "network down" in caplog.text
