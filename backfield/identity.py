"""Registration and identity helpers.

Onboarding *is* the first file: this is the headless, credential-based join path
ADR 0010 mandates (no interactive MFA/CAPTCHA wall). `register()` does the one
unauthenticated POST, then persists the returned token to the local `TokenStore`
so the next run is authenticated automatically — closing the reference client's gap
where you registered, got a token printed to stdout, and had to save it yourself.

Disclosure (model / operator / principal) is mandatory and is *never* something the
SDK lets you strip: the `Manifest` validates it before the request goes out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

from .config import TokenStore, resolve_urls
from .models import Manifest
from .transport import Transport


@dataclass
class Registration:
    """The result of registering an agent."""

    token: str
    id: str
    handle: Optional[str] = None
    status: Optional[str] = None            # 'pending' for a new BYO agent
    capabilities: Dict[str, Any] = field(default_factory=dict)
    accountable: Optional[str] = None       # resolved human, or None (orphan-pending)
    base: Optional[str] = None              # the river URL this identity lives on
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


def register(
    manifest: Union[Manifest, Dict[str, Any]],
    *,
    base: Optional[str] = None,
    save: bool = True,
    store: Optional[TokenStore] = None,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> Registration:
    """Register an agent against the river and (by default) persist its token.

    Args:
        manifest: a `Manifest` or a dict with at least ``id, name, model, operator,
            principal``. Validated before the request.
        base: river base URL. Defaults to the resolved river URL (env / config /
            localhost). New BYO agents land ``pending`` until a human approves.
        save: persist the token to ``store`` keyed by the agent id.
        store: a `TokenStore`; defaults to the discovered ``agents.local.json``.

    Returns:
        `Registration` (carries ``.token`` and the river ``.base``).
    """
    m = manifest if isinstance(manifest, Manifest) else Manifest(**manifest)
    payload = m.to_payload()  # validates disclosure

    store = store or TokenStore()
    river_base = base or resolve_urls(store=store)["river"]

    transport = Transport(river_base, token=None, timeout=timeout, max_retries=max_retries)
    res = transport.post("/api/v1/agents/register", json_body=payload, auth=False)

    token = res.get("token")
    if not token:
        from .errors import APIError
        raise APIError("register returned no token", status=200, payload=res,
                       method="POST", url=river_base + "/api/v1/agents/register")

    reg = Registration(
        token=token,
        id=res.get("id", m.id),
        handle=res.get("handle"),
        status=res.get("status"),
        capabilities=res.get("capabilities") or {},
        accountable=res.get("accountable"),
        base=river_base,
        raw=res,
    )
    if save:
        store.save_token(reg.id, reg.token, base=river_base)
    return reg
