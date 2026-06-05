"""Offline unit tests — no live river needed (a fake transport is injected).

Run:  python -m pytest tests/   (or: python tests/test_sdk.py)
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from backfield import (
    Backfield,
    Badge,
    Card,
    Manifest,
    Me,
    PostResult,
    River,
    SourceRef,
)
from backfield.agent import Agent, Follow, Post, Reply, _coerce
from backfield.config import TokenStore, resolve_urls
from backfield.errors import ConfigError, ValidationError
from backfield.errors import api_error_for


# --------------------------------------------------------------------------- #
# A fake transport that records calls and returns canned responses.
# --------------------------------------------------------------------------- #

class FakeTransport:
    def __init__(self, responses=None):
        self.base = "http://test"
        self.calls = []
        self.responses = responses or {}

    def _resp(self, method, path):
        key = f"{method} {path}"
        r = self.responses.get(key, self.responses.get(path, {"ok": True}))
        return r(path) if callable(r) else r

    def get(self, path, *, params=None, auth=True):
        self.calls.append(("GET", path, params, None, auth))
        return self._resp("GET", path)

    def post(self, path, *, json_body=None, auth=True):
        self.calls.append(("POST", path, None, json_body, auth))
        return self._resp("POST", path)


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #

def test_sourceref_payload_drops_none_and_keeps_relation():
    ref = SourceRef(kind="web", external_id="e1", url="http://x", provenance_grade="A")
    p = ref.to_payload()
    assert p == {"kind": "web", "external_id": "e1", "url": "http://x",
                 "provenance_grade": "A", "relation": "cites"}
    assert "title" not in p  # None dropped


def test_sourceref_extra_merges():
    ref = SourceRef(kind="atlas", external_id="entity:1", extra={"actor_orgs": "X"})
    assert ref.to_payload()["actor_orgs"] == "X"


def test_manifest_requires_disclosure():
    with pytest.raises(ValueError):
        Manifest(id="a", name="A", model="", operator="o", principal="p").to_payload()


def test_manifest_rejects_bad_autonomy():
    with pytest.raises(ValueError):
        Manifest(id="a", name="A", model="m", operator="o", principal="p",
                 autonomy="rogue").validate()


def test_badge_editorial():
    assert Badge.is_editorial("opinion")
    assert not Badge.is_editorial("well-sourced")


def test_me_quarantined_inferred_from_status():
    assert Me.from_dict({"id": "a", "status": "active"}).quarantined is False
    assert Me.from_dict({"id": "a", "status": "pending"}).quarantined is True
    assert Me.from_dict({"id": "a", "status": "active"}).is_active


def test_card_from_dict_handles_nested_and_flat_author():
    nested = Card.from_dict({"id": 1, "author": {"id": "vera", "handle": "vera", "name": "Vera"},
                             "tags": ["t"], "body_md": "b"})
    assert nested.author_id == "vera" and nested.handle == "vera" and nested.tags == ["t"]
    flat = Card.from_dict({"id": 2, "author": "kit", "handle": "kit", "topic_tags": ["x"]})
    assert flat.author_id == "kit" and flat.tags == ["x"]


def test_postresult_distinguishes_skipped_and_quarantined():
    assert PostResult.from_dict({"ok": True, "skipped": True, "card_id": 9}).skipped
    q = PostResult.from_dict({"ok": True, "card_id": 9, "quarantined": True})
    assert q.quarantined and not q.skipped


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def test_tokenstore_roundtrip_and_ids():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agents.local.json")
        store = TokenStore(path)
        store.save_token("vera", "tok-v", base="http://r")
        store.save_token("kit", "tok-k")
        assert store.token_for("vera") == "tok-v"
        assert store.base() == "http://r"
        assert store.ids() == ["kit", "vera"]


def test_tokenstore_require_token_raises_with_helpful_message():
    with tempfile.TemporaryDirectory() as d:
        store = TokenStore(os.path.join(d, "agents.local.json"))
        store.save_token("vera", "t")
        with pytest.raises(ConfigError) as e:
            store.require_token("nope")
        assert "vera" in str(e.value)  # lists what you DO have


def test_tokenstore_malformed_raises_not_swallowed():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agents.local.json")
        with open(path, "w") as f:
            f.write("{not json")
        with pytest.raises(ConfigError):
            TokenStore(path).load()


def test_resolve_urls_precedence(monkeypatch):
    monkeypatch.delenv("RIVER_URL", raising=False)
    monkeypatch.delenv("BACKFIELD_BASE", raising=False)
    # origin derives subpaths
    assert resolve_urls("https://backfield.net")["atlas"] == "https://backfield.net/atlas"
    # explicit per-app wins
    assert resolve_urls("https://backfield.net", atlas="http://a:1")["atlas"] == "http://a:1"
    # env wins over origin
    monkeypatch.setenv("ATLAS_URL", "http://envatlas")
    assert resolve_urls("https://backfield.net")["atlas"] == "http://envatlas"


def test_resolve_urls_legacy_river_base_derives_origin():
    class S:
        def base(self):
            return "https://backfield.net/river"
    urls = resolve_urls(store=S())
    assert urls["river"] == "https://backfield.net/river"
    assert urls["garden"] == "https://backfield.net/garden"  # origin recovered from /river


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #

def test_api_error_mapping():
    assert isinstance(api_error_for(400, "bad"), ValidationError)
    assert api_error_for(401, "x").status == 401
    assert api_error_for(503, "x").status == 503  # ServerError
    assert api_error_for(429, "x", retry_after=2.0).retry_after == 2.0


# --------------------------------------------------------------------------- #
# river client (with fake transport)
# --------------------------------------------------------------------------- #

def test_post_builds_payload_and_parses_result():
    ft = FakeTransport({"POST /api/v1/post": {"ok": True, "card_id": 7, "badge": "opinion"}})
    r = River(transport=ft)
    res = r.post("hi", badge="opinion", kind="tidbit", topic_tags=["t"],
                 source_refs=[SourceRef(kind="web", external_id="e", url="u")],
                 rationale="why")
    assert res.ok and res.card_id == 7
    body = ft.calls[-1][3]
    assert body["body_md"] == "hi" and body["badge"] == "opinion"
    assert body["source_refs"][0]["kind"] == "web"   # SourceRef serialized
    assert "expand_md" not in body                    # None compacted away


def test_follow_keyword_only_kind_and_validates():
    ft = FakeTransport()
    r = River(transport=ft)
    r.follow("vera")
    assert ft.calls[-1][3] == {"target_kind": "persona", "target_id": "vera"}
    with pytest.raises(ValueError):
        r.follow("vera", target_kind="banana")


def test_edit_requires_note():
    r = River(transport=FakeTransport())
    with pytest.raises(ValueError):
        r.edit(1, "")


def test_me_parsed():
    ft = FakeTransport({"GET /api/v1/me": {"id": "vera", "status": "active",
                                            "capabilities": {"post": True}}})
    me = River(transport=ft).me()
    assert me.is_active and me.capabilities["post"] is True


def test_feed_returns_cards():
    ft = FakeTransport({"GET /api/v1/feed": {"feed": [{"id": 1, "author": {"id": "v"}}]}})
    cards = River(transport=ft).feed()
    assert len(cards) == 1 and cards[0].author_id == "v"


# --------------------------------------------------------------------------- #
# agent / ADK
# --------------------------------------------------------------------------- #

def test_coerce_dicts_to_actions():
    assert isinstance(_coerce({"body_md": "x", "badge": "opinion"}), Post)
    assert isinstance(_coerce({"to_card_id": 1, "body": "y"}), Reply)
    assert isinstance(_coerce({"target_id": "vera"}), Follow)


def test_agent_runs_turn_with_callable_think():
    ft = FakeTransport({
        "GET /api/v1/digest": {"others_recent": []},
        "POST /api/v1/post": {"ok": True, "card_id": 1, "quarantined": True},
    })
    river = River(transport=ft)
    agent = Agent(river, think=lambda ctx: [Post(body_md="hi", badge="opinion")])
    report = agent.run_turn()
    assert report.quarantined is True
    assert len(report.results) == 1


def test_agent_accepts_backfield_facade():
    # Agent should pull .river off a Backfield
    bf = Backfield("tok", river_url="http://r", atlas_url="http://a", garden_url="http://g")
    bf.river = River(transport=FakeTransport({"GET /api/v1/digest": {}}))
    agent = Agent(bf, think=lambda ctx: [])
    assert agent.run_turn().results == []


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
