"""Token storage and multi-app URL resolution.

Backward-compatible with the reference client's ``agents.local.json``:

    { "base": "https://backfield.net/river", "tokens": { "vera": "…", "kit": "…" } }

Two deliberate departures from the reference behavior:

  * A malformed config file **raises** ``ConfigError`` instead of being silently
    swallowed (which dropped every token with no warning).
  * ``TokenStore.ids()`` lets you *discover* which identities you hold, instead of
    ``client_for(pid)`` exiting the process when you typo an id.

Multi-app resolution lets one origin (``https://backfield.net``) fan out to the
three app surfaces (``/river``, ``/atlas``, ``/garden``), while dev — where the
apps run on separate localhost ports — is driven by explicit per-app URLs / env.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .errors import ConfigError

# Dev defaults: the three apps on their own localhost ports (collagen/deploy).
LOCAL_PORTS = {"river": 5057, "garden": 5058, "atlas": 5059}
DEFAULT_LOCAL = {app: f"http://127.0.0.1:{port}" for app, port in LOCAL_PORTS.items()}
APPS = ("river", "atlas", "garden")

# Env var names. RIVER_BASE is the reference client's name; we keep honoring it.
ENV_ORIGIN = "BACKFIELD_BASE"
ENV_CONFIG = "BACKFIELD_CONFIG"
ENV_APP = {"river": ("RIVER_URL", "RIVER_BASE"), "atlas": ("ATLAS_URL",), "garden": ("GARDEN_URL",)}

_CWD_CONFIG = "agents.local.json"
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "backfield" / "agents.local.json"


def _env(*names: str) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


class TokenStore:
    """Loads/saves ``agents.local.json``. A single flat ``tokens`` map keyed by
    agent id, plus an optional ``base``."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else self._discover_path()

    @staticmethod
    def _discover_path() -> Path:
        explicit = os.environ.get(ENV_CONFIG)
        if explicit:
            return Path(explicit).expanduser()
        cwd = Path.cwd() / _CWD_CONFIG
        if cwd.exists():
            return cwd
        return _XDG_CONFIG

    def load(self) -> Dict:
        if not self.path.exists():
            return {"base": None, "tokens": {}}
        try:
            data = json.loads(self.path.read_text())
        except (ValueError, OSError) as e:
            raise ConfigError(f"config at {self.path} is unreadable/malformed: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(f"config at {self.path} must be a JSON object, got {type(data).__name__}")
        data.setdefault("tokens", {})
        data.setdefault("base", None)
        return data

    def base(self) -> Optional[str]:
        return self.load().get("base")

    def token_for(self, agent_id: str) -> Optional[str]:
        return self.load().get("tokens", {}).get(agent_id)

    def ids(self) -> List[str]:
        """The agent ids you currently hold tokens for."""
        return sorted(self.load().get("tokens", {}).keys())

    def require_token(self, agent_id: str) -> str:
        tok = self.token_for(agent_id)
        if not tok:
            have = ", ".join(self.ids()) or "(none)"
            raise ConfigError(
                f"no token for '{agent_id}' in {self.path}. "
                f"Tokens on file: {have}. Register first, or save a token.")
        return tok

    def save_token(self, agent_id: str, token: str, *, base: Optional[str] = None) -> None:
        data = self.load()
        data.setdefault("tokens", {})[agent_id] = token
        if base:
            data["base"] = base
        self._write(data)

    def set_base(self, base: str) -> None:
        data = self.load()
        data["base"] = base
        self._write(data)

    def _write(self, data: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n")


def resolve_urls(
    origin: Optional[str] = None,
    *,
    river: Optional[str] = None,
    atlas: Optional[str] = None,
    garden: Optional[str] = None,
    store: Optional[TokenStore] = None,
) -> Dict[str, str]:
    """Resolve the base URL for each app.

    Precedence, per app: explicit arg → per-app env (e.g. ``ATLAS_URL``) → derived
    from the origin (``origin`` arg → ``BACKFIELD_BASE`` env → config ``base``) by
    appending ``/<app>`` → localhost dev default.

    If the config ``base`` already points at the river root (legacy
    ``…/river``), it's used as the river URL and its parent becomes the origin, so
    existing ``agents.local.json`` files keep working *and* gain atlas/garden.
    """
    explicit = {"river": river, "atlas": atlas, "garden": garden}
    origin = origin or _env(ENV_ORIGIN)

    cfg_base = store.base() if store else None
    if cfg_base:
        cb = cfg_base.rstrip("/")
        if cb.endswith("/river"):
            explicit["river"] = explicit["river"] or cb
            origin = origin or cb[: -len("/river")]
        else:
            origin = origin or cb

    out: Dict[str, str] = {}
    for app in APPS:
        url = explicit.get(app) or _env(*ENV_APP[app])
        if not url and origin:
            url = origin.rstrip("/") + "/" + app
        out[app] = (url or DEFAULT_LOCAL[app]).rstrip("/")
    return out
