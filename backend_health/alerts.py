from __future__ import annotations

import logging
import os
from typing import Protocol

import requests

log = logging.getLogger("backend_health.alerts")

WEBHOOK_ENV_VAR = "BACKEND_HEALTH_ALERT_WEBHOOK"


class Alerter(Protocol):
    def notify(self, tenant_id: str, consecutive_failures: int, error: str | None) -> None: ...


class LoggingAlerter:
    """Default alerter: logs a clearly-marked ALERT line.

    Used in demo mode and whenever no webhook is configured, so a failing
    tenant is always visible in the run's own logs even with no external
    integration set up.
    """

    def notify(self, tenant_id: str, consecutive_failures: int, error: str | None) -> None:
        log.error(
            "ALERT: tenant %s has failed %d consecutive runs. Last error: %s",
            tenant_id,
            consecutive_failures,
            error,
        )


class WebhookAlerter:
    """Posts a JSON payload to an incoming webhook (Slack-compatible shape).

    Best-effort: a webhook failure is logged, never raised, so a broken alert
    channel cannot fail the ingestion run itself.
    """

    def __init__(self, url: str, *, session: requests.Session | None = None, timeout: float = 10.0):
        self.url = url
        self._session = session or requests.Session()
        self.timeout = timeout

    def notify(self, tenant_id: str, consecutive_failures: int, error: str | None) -> None:
        text = (
            f":rotating_light: Backend Health: tenant `{tenant_id}` has failed "
            f"{consecutive_failures} consecutive runs. Last error: {error}"
        )
        try:
            resp = self._session.post(self.url, json={"text": text}, timeout=self.timeout)
            if resp.status_code >= 300:
                log.error("alert webhook returned HTTP %d", resp.status_code)
        except requests.RequestException as exc:
            log.error("failed to post alert webhook: %s", exc)


def get_alerter(webhook_url: str | None = None) -> Alerter:
    """Return a WebhookAlerter if a URL is configured (arg or env var), else LoggingAlerter."""
    url = webhook_url or os.environ.get(WEBHOOK_ENV_VAR)
    if url:
        return WebhookAlerter(url)
    return LoggingAlerter()
