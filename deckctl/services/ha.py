"""Home Assistant REST client.

Thin wrapper over urllib for service calls and state reads. Secrets come
from `~/.config/deckctl/secrets.env` (HA_URL, HA_TOKEN); if either is
missing the service constructs but logs and refuses calls.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class HAService:
    def __init__(self, url: str | None, token: str | None):
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        # SSE state subscription bookkeeping. The reader thread is lazily
        # started on first subscribe so we don't open a stream we won't use.
        self._sse_lock = threading.Lock()
        self._sse_thread: threading.Thread | None = None
        self._state_subs: dict[str, list[Callable[[dict], None]]] = {}

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

    # ─── state subscriptions (SSE) ─────────────────────────────────────────

    def subscribe_state(
        self, entity_id: str, callback: Callable[[dict], None]
    ) -> Callable[[], None]:
        """Fire `callback(new_state_dict)` when `entity_id` changes.

        First subscribe lazily starts a background thread that streams
        `/api/stream?restrict=state_changed`. Returns an unsubscribe
        function the widget MUST call on dispose.
        """
        with self._sse_lock:
            self._state_subs.setdefault(entity_id, []).append(callback)
            self._ensure_sse_started()

        def unsubscribe() -> None:
            with self._sse_lock:
                try:
                    self._state_subs[entity_id].remove(callback)
                except (KeyError, ValueError):
                    pass

        return unsubscribe

    def _ensure_sse_started(self) -> None:
        if self._sse_thread is not None or not self.configured:
            return
        self._sse_thread = threading.Thread(
            target=self._sse_loop, name="ha-sse", daemon=True,
        )
        self._sse_thread.start()

    def _sse_loop(self) -> None:
        """Stream `/api/stream` events with reconnect-on-error."""
        url = f"{self.url}/api/stream?restrict=state_changed"
        headers = {"Authorization": f"Bearer {self.token}"}
        backoff = 1.0
        while True:
            try:
                req = Request(url, headers=headers)
                # No timeout — server keeps the connection open and pushes.
                resp = urlopen(req)
                log.info("ha: sse connected")
                backoff = 1.0
                self._read_sse_stream(resp)
            except (HTTPError, URLError, TimeoutError) as e:
                log.warning("ha: sse connection failed: %s", e)
            except Exception:
                log.exception("ha: sse loop raised")
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)

    def _read_sse_stream(self, resp) -> None:
        """Parse the text/event-stream body line by line."""
        for raw in resp:
            try:
                line = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "ping":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") != "state_changed":
                continue
            data = event.get("data") or {}
            entity_id = data.get("entity_id")
            new_state = data.get("new_state")
            if entity_id and isinstance(new_state, dict):
                self._dispatch_state(entity_id, new_state)

    def _dispatch_state(self, entity_id: str, state: dict) -> None:
        with self._sse_lock:
            cbs = list(self._state_subs.get(entity_id, []))
        for cb in cbs:
            try:
                cb(state)
            except Exception:
                log.exception("ha state subscriber raised for %s", entity_id)
