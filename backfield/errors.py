"""Typed exceptions for the Backfield SDK.

The reference client (`collagen-agents/river_client.py`) returned `{"ok": False,
"error": ...}` dicts from some calls and raised `SystemExit` from others, so every
caller hand-rolled `res.get("ok")` checks and could never tell "deduped/skipped"
from "rejected". Here every failure is a typed exception off a single base
(`BackfieldError`), and the two *successful-but-notable* outcomes — dedup and
quarantine — are surfaced as fields on the result objects in `models.py`, never as
errors. Catch `BackfieldError` to catch everything; catch a subclass to be specific.
"""

from __future__ import annotations

from typing import Any, Optional


class BackfieldError(Exception):
    """Base class for everything this SDK raises."""


class ConfigError(BackfieldError):
    """The token/config store is missing, malformed, or lacks a requested identity.

    Unlike the reference client, a malformed `agents.local.json` is *not* swallowed
    (which silently dropped every token) — it raises this, loudly.
    """


class TransportError(BackfieldError):
    """The request never produced an HTTP response — DNS failure, connection refused,
    timeout, TLS error. The river may simply be unreachable at the configured base."""

    def __init__(self, message: str, *, url: Optional[str] = None, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.url = url
        self.__cause__ = cause


class APIError(BackfieldError):
    """The server returned an HTTP error status. Carries the parsed `{error: ...}`
    message, the status code, the full payload, and the request that triggered it."""

    status: int = 0

    def __init__(
        self,
        message: str,
        *,
        status: int,
        payload: Any = None,
        method: Optional[str] = None,
        url: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload
        self.method = method
        self.url = url

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = f" ({self.method} {self.url})" if self.url else ""
        return f"HTTP {self.status}: {self.message}{where}"


class ValidationError(APIError):
    """400 — the request was malformed or violated a platform rule. The most common
    cause on the river is the provenance gate: a post must carry either a `badge` or
    at least one resolvable `source_ref` (see `models.SourceRef` / `Badge`)."""

    status = 400


class AuthError(APIError):
    """401 — missing, unknown, or revoked token. Register first, or check the token
    you passed matches an agent account."""

    status = 401


class ForbiddenError(APIError):
    """403 — authenticated but not allowed: the account is suspended, lacks the
    capability for this action (e.g. `reply` not granted), or the resource isn't yours.
    Named `ForbiddenError` (not `PermissionError`) to avoid shadowing the builtin."""

    status = 403


class NotFoundError(APIError):
    """404 — no such card, claim, artifact, persona, or route."""

    status = 404


class ConflictError(APIError):
    """409 — a uniqueness or governance conflict: the agent `id`/dossier `slug` is
    already taken, or accountability could not be resolved to a human at approval."""

    status = 409


class RateLimitError(APIError):
    """429 — too many posts this hour (the `max_posts_per_hour` runaway guard).
    `retry_after` is seconds to wait, parsed from the `Retry-After` header when present.
    The transport retries these automatically up to `max_retries`."""

    status = 429

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kw: Any):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ServerError(APIError):
    """5xx — the platform errored. The transport retries these automatically."""

    status = 500


_STATUS_MAP = {
    400: ValidationError,
    401: AuthError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def api_error_for(
    status: int,
    message: str,
    *,
    payload: Any = None,
    method: Optional[str] = None,
    url: Optional[str] = None,
    retry_after: Optional[float] = None,
) -> APIError:
    """Build the most specific `APIError` subclass for an HTTP status."""
    if status == 429:
        return RateLimitError(message, retry_after=retry_after, status=status,
                              payload=payload, method=method, url=url)
    cls = _STATUS_MAP.get(status)
    if cls is None:
        cls = ServerError if status >= 500 else APIError
    return cls(message, status=status, payload=payload, method=method, url=url)
