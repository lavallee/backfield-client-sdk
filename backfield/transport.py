"""The single HTTP chokepoint every client call flows through.

The reference client copy-pasted the same `urlopen` / `HTTPError` / `URLError`
block into five places, with no retries, no backoff, and no rate-limit awareness —
a third party hammering a shared river got bare failures. This consolidates all of
that into one `Transport`:

  * one place that builds URLs, headers, and JSON bodies;
  * automatic retry with exponential backoff + jitter on 429 / 5xx / connection
    errors, honoring `Retry-After`;
  * `{error: ...}` parsing into the typed exceptions in `errors.py`.

stdlib only (`urllib`) — no `requests`, no transitive deps.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional

from .errors import TransportError, api_error_for
from .version import __version__

USER_AGENT = f"backfield-sdk/{__version__} (+https://backfield.net)"

# Statuses worth retrying: rate limit + transient server errors.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class Transport:
    """A thin, retrying JSON-over-HTTP client bound to one app's base URL.

    Args:
        base: the app root, e.g. ``https://backfield.net/river`` or
            ``http://127.0.0.1:5057``. Endpoint paths are appended to it.
        token: optional Bearer token, sent on calls made with ``auth=True``.
        timeout: per-request timeout in seconds.
        max_retries: how many times to retry a retryable failure (0 disables).
        backoff: base seconds for exponential backoff (``backoff * 2**attempt``).
    """

    def __init__(
        self,
        base: str,
        token: Optional[str] = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        user_agent: str = USER_AGENT,
    ):
        if not base:
            raise ValueError("Transport requires a base URL")
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.user_agent = user_agent

    # -- public ---------------------------------------------------------------

    def get(self, path: str, *, params: Optional[Mapping[str, Any]] = None, auth: bool = True) -> Any:
        return self.request("GET", path, params=params, auth=auth)

    def post(self, path: str, *, json_body: Optional[Mapping[str, Any]] = None, auth: bool = True) -> Any:
        return self.request("POST", path, json_body=json_body, auth=auth)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        auth: bool = True,
    ) -> Any:
        """Make one request (with retries) and return the parsed JSON body.

        Raises a typed ``APIError`` on an HTTP error status and ``TransportError``
        if the request never reached the server. Retrying a POST is safe: the river
        deduplicates identical content server-side (returns ``skipped: true``).
        """
        url = self._url(path, params)
        data = None
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        attempt = 0
        while True:
            try:
                return self._once(method, url, data, headers)
            except _Retryable as r:
                if attempt >= self.max_retries:
                    raise r.error
                delay = r.retry_after if r.retry_after is not None else self._backoff(attempt)
                time.sleep(delay)
                attempt += 1

    # -- internals ------------------------------------------------------------

    def _url(self, path: str, params: Optional[Mapping[str, Any]]) -> str:
        url = self.base + ("" if path.startswith("/") else "/") + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
        return url

    def _backoff(self, attempt: int) -> float:
        # exponential backoff with full jitter, capped
        return min(8.0, self.backoff * (2 ** attempt)) * (0.5 + random.random() / 2)

    def _once(self, method: str, url: str, data: Optional[bytes], headers: Mapping[str, str]) -> Any:
        req = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            self._raise_http_error(e, method, url)
        except urllib.error.URLError as e:
            # connection-level failure — retryable
            raise _Retryable(TransportError(
                f"river unreachable at {url}: {getattr(e, 'reason', e)}", url=url, cause=e))
        except (TimeoutError, OSError) as e:  # socket timeout, reset, etc.
            raise _Retryable(TransportError(f"request to {url} failed: {e}", url=url, cause=e))
        return _parse_json(raw)

    def _raise_http_error(self, e: "urllib.error.HTTPError", method: str, url: str) -> "Any":
        try:
            body = e.read()
        except Exception:
            body = b""
        payload = _parse_json(body, default=None)
        message = _error_message(payload, fallback=str(e))
        retry_after = _retry_after_seconds(e.headers.get("Retry-After") if e.headers else None)
        err = api_error_for(e.code, message, payload=payload, method=method, url=url,
                            retry_after=retry_after)
        if e.code in _RETRY_STATUSES:
            raise _Retryable(err, retry_after=retry_after)
        raise err


class _Retryable(Exception):
    """Internal: wraps an error the request loop may retry."""

    def __init__(self, error: Exception, *, retry_after: Optional[float] = None):
        super().__init__(str(error))
        self.error = error
        self.retry_after = retry_after


def _parse_json(raw: bytes, default: Any = "__raise__") -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        if default == "__raise__":
            # A 2xx that isn't JSON (e.g. an HTML page) — return the text so the
            # caller isn't left with nothing.
            return raw.decode("utf-8", "replace")
        return default


def _error_message(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            if payload.get(key):
                return str(payload[key])
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:300]
    return fallback


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None  # HTTP-date form unsupported; fall back to computed backoff
