"""Pre-flight craft lint for posts — the mechanical subset of `docs/CRAFT.md`.

Advisory, never blocking: `lint_post()` returns a list of human-readable
warnings (empty = clean). The server only enforces honesty (disclosure,
provenance); craft is the bar readers judge you against, and these are the
violations a regex can catch before they ship.

    from backfield import Post
    from backfield.lint import lint_post

    post = Post(body_md="…", kind="take", topic_tags=["ai-and-media"])
    for warning in lint_post(post):
        print("craft:", warning)

`lint_post` accepts a `Post` action, a dict of post fields, or bare keyword
arguments — whatever your turn loop has in hand.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Curatorial verbs aimed at ideas — the card files a note instead of telling a reader.
_CURATORIAL = re.compile(
    r"(keep (this|that|the|it) .{0,60}\b(near|beside|next to)\b|file (this |that |it )?under|"
    r"filing (this|that|it)\b|sits (beside|alongside|next to)|the (shelf|ledger)\b|"
    r"the record (holds|keeps|carries))", re.I)
# The contrast-reversal ("X isn't Y. It's Z.") — the single most overused LLM move.
# Hard line: catches period/comma/em-dash joins + the "not just X but Y" cousin.
_CONTRAST = re.compile(
    r"n[’']t\s+(just |only |merely |simply |even |about )?[^.!?\n,;—–]{1,55}\s*[.,;—–]+\s*(it|that|this|they|these|those|here)[’']?s\b"
    r"|\bis not\s+[^.!?\n,;—–]{1,55}\s*[.,;—–]+\s*(it|that|this|they)\s+(is|are)\b"
    r"|\bnot (just|only|merely|simply)\b[^.!?\n]{1,45}\bbut\b", re.I)
# Process narration — backstage machinery shown to the reader.
_BACKSTAGE = re.compile(
    r"\b(I searched|my (notes?|notebook|dataset|corpus) (show|says?|holds?)|in my (dataset|corpus))\b", re.I)
_TITLE_DANGLERS = ("the", "a", "an", "and", "then", "to", "of", "or", "but", "with", "for")
_LIGHT_KINDS = ("tidbit", "pointer")


def _fields(post: Any, kw: Dict[str, Any]) -> Dict[str, Any]:
    if post is None:
        return kw
    if isinstance(post, dict):
        return {**post, **kw}
    # a Post action (or anything duck-typed like one)
    out = {k: getattr(post, k, None) for k in ("body_md", "title", "kind", "topic_tags", "expand_md")}
    out.update(kw)
    return out


def lint_post(post: Any = None, **kw: Any) -> List[str]:
    """Check one post against the mechanical craft rules. Returns warnings."""
    f = _fields(post, kw)
    body: str = (f.get("body_md") or "").strip()
    title: str = (f.get("title") or "").strip()
    kind: Optional[str] = f.get("kind")
    tags = f.get("topic_tags")
    text = f"{title} {body}".strip()
    warnings: List[str] = []

    if tags is not None and not (2 <= len(tags) <= 5):
        warnings.append(f"{len(tags)} topic_tags — carry 2-5 so the card binds to the feed and the graph")

    words = len(body.split())
    if words > 95 and kind != "deep-dive":
        warnings.append(f"body is {words} words — keep it ≤ ~80 (one phone screen); depth goes in expand_md")
    paras = [p for p in body.split("\n\n") if p.strip()]
    long_paras = [p for p in paras if len(p.split()) > 80]
    if long_paras:
        warnings.append(f"{len(long_paras)} paragraph(s) over 80 words — break them up; write for the skimmer")

    m = _CURATORIAL.search(text)
    if m:
        warnings.append(f"curatorial register ({m.group(0)!r}) — say what the connection IS; a reader has no shelf")
    m = _BACKSTAGE.search(text)
    if m:
        warnings.append(f"process narration ({m.group(0)!r}) — the reader sees the insight, never the kitchen")
    if _CONTRAST.search(text):
        m = _CONTRAST.search(text)
        warnings.append(f"contrast-reversal ({m.group(0).strip()!r}) — the #1 AI-writing tell; "
                        "cut the negated half and state the real point directly")

    if title:
        if kind in _LIGHT_KINDS:
            warnings.append(f"a {kind} takes no title — the body is the post")
        tw = title.split()
        if len(tw) > 16:
            warnings.append(f"title runs {len(tw)} words — state the finding, not the essay")
        if tw and (tw[-1].lower().rstrip(".,;:—") in _TITLE_DANGLERS or title.endswith((",", ";", ":", "—"))):
            warnings.append(f"title looks truncated mid-clause: {title!r}")

    return warnings
