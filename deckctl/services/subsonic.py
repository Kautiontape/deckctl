"""Subsonic API client (works with Navidrome, Airsonic, etc.).

Used for actions Feishin's MPRIS doesn't expose — currently only
star/unstar. Credentials can be set explicitly via secrets.env
(SUBSONIC_URL, SUBSONIC_CRED) or auto-extracted from Feishin's local
storage as a fallback.

The credential string is the standard Subsonic auth-by-token format:
"u=USER&s=SALT&t=md5(password+salt)". Pasted directly into URL params.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

log = logging.getLogger(__name__)

API_VERSION = "1.16.1"
CLIENT_NAME = "deckctl"

# How long to trust an auto-extracted credential before re-extracting.
EXTRACT_CACHE_SECONDS = 300

# Best place to find Feishin's currently-active server creds. We grep
# `strings` output of leveldb files for currentServer JSON. Order matters:
# IndexedDB tends to have the freshest entry.
_FEISHIN_STORAGE_PATHS = [
    "~/.config/feishin/IndexedDB/file__0.indexeddb.leveldb",
    "~/.config/feishin/Local Storage/leveldb",
]

_BLOCK_RE = re.compile(r'"currentServer"\s*:\s*\{')
_CRED_RE = re.compile(r'"credential"\s*:\s*"(u=[^"]+)"')
_URL_RE = re.compile(r'"url"\s*:\s*"(http[^"]+)"')


def _extract_from_feishin() -> tuple[str, str] | None:
    """Best-effort scan of Feishin's storage for (url, credential).

    The IndexedDB / LevelDB files contain many serialized state snapshots.
    For each `"currentServer":{` opening, we look ~2KB forward and pair
    the first `credential` and `url` we see (Feishin emits them in that
    same flat object).
    """
    for raw_path in _FEISHIN_STORAGE_PATHS:
        root = Path(raw_path).expanduser()
        if not root.exists():
            continue
        # Newest files first — credentials rotate, freshest entry is the
        # one we want.
        files = sorted(
            (p for p in root.rglob("*") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files:
            try:
                out = subprocess.check_output(
                    ["strings", str(f)], text=True, timeout=5
                )
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
            for block_match in _BLOCK_RE.finditer(out):
                window = out[block_match.end():block_match.end() + 2000]
                cred_m = _CRED_RE.search(window)
                url_m = _URL_RE.search(window)
                if cred_m and url_m:
                    return url_m.group(1).rstrip("/"), cred_m.group(1)
    return None


class SubsonicService:
    def __init__(self, url: str | None, credential: str | None):
        self._explicit_url = (url or "").rstrip("/") or None
        self._explicit_cred = credential or None
        self._cache_lock = threading.Lock()
        self._cached: tuple[float, str, str] | None = None  # (ts, url, cred)

    def _resolve_creds(self) -> tuple[str, str] | None:
        if self._explicit_url and self._explicit_cred:
            return self._explicit_url, self._explicit_cred
        with self._cache_lock:
            if self._cached is not None:
                ts, url, cred = self._cached
                if time.time() - ts < EXTRACT_CACHE_SECONDS:
                    return url, cred
            extracted = _extract_from_feishin()
            if extracted is None:
                return None
            url, cred = extracted
            self._cached = (time.time(), url.rstrip("/"), cred)
            return self._cached[1], self._cached[2]

    @property
    def configured(self) -> bool:
        return self._resolve_creds() is not None

    def _call(self, endpoint: str, params: dict) -> dict | None:
        creds = self._resolve_creds()
        if creds is None:
            log.info("subsonic: no creds available")
            return None
        base, cred = creds
        # Credential is already in URL-param form: u=USER&s=SALT&t=TOKEN.
        # Append our params plus required v/c/f.
        suffix = urlencode({**params, "v": API_VERSION, "c": CLIENT_NAME, "f": "json"})
        url = f"{base}/rest/{endpoint}?{cred}&{suffix}"
        try:
            with urlopen(url, timeout=4) as resp:
                data = json.loads(resp.read())
        except (HTTPError, URLError, ValueError, TimeoutError):
            log.exception("subsonic: %s failed", endpoint)
            return None
        # Check the canonical envelope.
        envelope = data.get("subsonic-response", {})
        if envelope.get("status") != "ok":
            log.warning("subsonic: %s returned %r", endpoint, envelope.get("error"))
            return None
        return envelope

    # ─── public API ────────────────────────────────────────────────────────

    def star(self, track_id: str) -> bool:
        if not track_id:
            return False
        return self._call("star", {"id": track_id}) is not None

    def unstar(self, track_id: str) -> bool:
        if not track_id:
            return False
        return self._call("unstar", {"id": track_id}) is not None

    def is_starred(self, track_id: str) -> bool:
        """Returns True if `track_id` is in the user's starred list.

        Calls getSong (cheap, returns one record). The `starred` field is
        present on the song when starred; absent otherwise.
        """
        if not track_id:
            return False
        env = self._call("getSong", {"id": track_id})
        if env is None:
            return False
        song = env.get("song", {})
        return "starred" in song
