"""Craft lint + CRAFT_PROMPT — the advisory writing-bar layer."""

from __future__ import annotations

import pytest

from backfield import CRAFT_PROMPT, lint_post
from backfield.agent import Post


def _has(warnings, fragment):
    return any(fragment in w for w in warnings)


def test_clean_post_passes():
    assert lint_post(body_md="Reuters cut 40 jobs from its graphics desk Tuesday.\n\n"
                             "The union says nobody was consulted.",
                     kind="signal", topic_tags=["reuters", "labor"]) == []


def test_curatorial_register_flagged():
    w = lint_post(body_md="Keep the HÄRTING gaming-law analysis near the newsroom AI "
                          "enforcement conversation.", topic_tags=["law", "ai"])
    assert _has(w, "curatorial register")


def test_record_holds_flagged():
    w = lint_post(body_md="OpenAI keeps a running index of its deals. The record holds the page.",
                  topic_tags=["openai", "licensing"])
    assert _has(w, "curatorial register")


def test_contrast_reversal_flagged():
    w = lint_post(body_md="This isn't licensing. It's an ad network built inside an answer engine.",
                  topic_tags=["licensing", "platforms"])
    assert _has(w, "contrast-reversal")


def test_process_narration_flagged():
    w = lint_post(body_md="I searched for a week and my notes show three matching deals.",
                  topic_tags=["deals", "ai"])
    assert _has(w, "process narration")


def test_em_dashes_not_flagged():
    # Em-dashes are fine (operator decision 2026-06-11) — no warning, ever.
    w = lint_post(body_md="The deal — announced Tuesday — covers text — and maybe video.",
                  topic_tags=["deals", "ai"])
    assert not _has(w, "em-dash")


def test_contrast_reversal_variants_flagged():
    # comma join and em-dash join, plus the "not just X but Y" cousin
    assert _has(lint_post(body_md="This isn't licensing, it's an ad network.", topic_tags=["a", "b"]),
                "contrast-reversal")
    assert _has(lint_post(body_md="The threat isn't a clever exploit — it's a slop flood.", topic_tags=["a", "b"]),
                "contrast-reversal")
    assert _has(lint_post(body_md="It's not just a feature but a whole platform.", topic_tags=["a", "b"]),
                "contrast-reversal")
    # the good rewrite (no negated strawman) is clean
    assert not _has(lint_post(body_md="It's an ad network built inside an answer engine.", topic_tags=["a", "b"]),
                    "contrast-reversal")


def test_tag_count_bounds():
    assert _has(lint_post(body_md="x", topic_tags=["one"]), "topic_tags")
    assert _has(lint_post(body_md="x", topic_tags=list("abcdef")), "topic_tags")
    assert not _has(lint_post(body_md="x", topic_tags=["a", "b"]), "topic_tags")


def test_long_body_flagged_except_deep_dive():
    body = "word " * 120
    assert _has(lint_post(body_md=body, topic_tags=["a", "b"], kind="take"), "body is")
    assert not _has(lint_post(body_md=body, topic_tags=["a", "b"], kind="deep-dive"), "body is")


def test_wall_of_text_flagged():
    w = lint_post(body_md="sentence " * 90, topic_tags=["a", "b"], kind="deep-dive")
    assert _has(w, "paragraph")


def test_title_rules():
    assert _has(lint_post(body_md="x", topic_tags=["a", "b"], kind="tidbit", title="A title"),
                "takes no title")
    assert _has(lint_post(body_md="x", topic_tags=["a", "b"], kind="take",
                          title="Coding agents are becoming a preview of editorial agents: autonomy rises, then"),
                "truncated")
    assert _has(lint_post(body_md="x", topic_tags=["a", "b"], kind="take",
                          title=" ".join(["word"] * 20)), "title runs")


def test_accepts_post_action_and_dict():
    p = Post(body_md="The record holds the page.", kind="take", topic_tags=["a", "b"])
    assert _has(lint_post(p), "curatorial register")
    assert _has(lint_post({"body_md": "The record holds the page.", "topic_tags": ["a", "b"]}),
                "curatorial register")


def test_craft_prompt_is_substantive():
    assert "WRITE TO THE READER" in CRAFT_PROMPT
    assert "REPLY or a QUOTE-POST" in CRAFT_PROMPT
    assert len(CRAFT_PROMPT) > 1500


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
