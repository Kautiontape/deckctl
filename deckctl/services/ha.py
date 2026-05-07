"""Home Assistant REST client.

Thin wrapper over urllib for service calls and state reads. Secrets come
from `~/.config/deckctl/secrets.env` (HA_URL, HA_TOKEN); if either is
missing the service constructs but logs and refuses calls.
"""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class HAService:
    def __init__(self, url: str | None, token: str | None):
        self.url = (url or "").rstrip("/")
        self.token = token or ""

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | None = None,
        data: dict | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Fire-and-forget service call. Returns True on 2xx."""
        if not self.configured:
            log.warning("ha: not configured (HA_URL/HA_TOKEN missing)")
            return False
        body: dict = dict(data or {})
        if entity_id:
            body["entity_id"] = entity_id
        endpoint = f"{self.url}/api/services/{domain}/{service}"
        req = Request(
            endpoint,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    return True
                log.warning("ha: %s.%s -> HTTP %s", domain, service, resp.status)
                return False
        except HTTPError as e:
            log.warning("ha: %s.%s HTTP %s: %s", domain, service, e.code, e.reason)
        except (URLError, TimeoutError):
            log.exception("ha: %s.%s failed", domain, service)
        return False

    def state(self, entity_id: str, timeout: float = 5.0) -> dict | None:
        """Returns the entity's state dict, or None on failure."""
        if not self.configured:
            return None
        endpoint = f"{self.url}/api/states/{entity_id}"
        req = Request(
            endpoint,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (HTTPError, URLError, ValueError, TimeoutError):
            log.exception("ha: state read for %s failed", entity_id)
        return None
