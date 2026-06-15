# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** — the operating map for this repo (what the SDK is, the module
map, the invariants, the writing bar, and the dev/test/release workflow). It applies to Claude
Code, Codex, and human contributors alike.

Quick reminders that bite if you forget them:

- **Zero runtime dependencies** (stdlib only) — never add a runtime dep to `pyproject.toml`.
- **The contract is the API** — this package never imports the river's server code.
- **Bump `backfield/version.py` + add a `CHANGELOG.md` entry** for every user-visible change.
- **Keep `python -m pytest tests/ -q` green.**
- **Populate `SourceRef.source_date`** — it drives the age-chip and the freshness lint.
