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
from datetime import date
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

# Freshness (CRAFT rule 12). The river renders a publication-age chip from a source's
# source_date; a grounded post whose freshest source is older than this should FRAME the
# recency — tie it to the current moment, or say plainly it's older (ICYMI / a fresh peg) —
# never present dated material as today's news. Older-with-context is welcome; this only
# flags the unframed case. Tune via FRESH_DAYS.
FRESH_DAYS = 180
# Temporal-context signals that earn an older source its place (a year/month reference or
# recency/update language). Their presence means the post frames the recency, so no warning.
_RECENCY_CONTEXT = re.compile(
    r"\b(since|as of|originally|back in|has since|have since|revisit\w*|still|"
    r"\d+\s+(?:months?|years?|weeks?)\s+(?:ago|later)|at the time|earlier this year|last year|"
    r"first (?:reported|announced|launched|introduced)|icymi|in 20\d{2}|20\d{2})\b", re.I)


def _parse_src_date(s: Any) -> Optional[date]:
    """A date from a source_date string: full YYYY-MM-DD, else year-only -> Jan 1. Else None."""
    if not s:
        return None
    s = str(s)
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(20\d{2})\b", s)
    if m:
        try:
            return date(int(m.group(1)), 1, 1)
        except ValueError:
            return None
    return None


def _freshest_source_date(source_refs: Any) -> Optional[date]:
    """The most recent parseable source_date across a post's source_refs (SourceRef|dict)."""
    dates = []
    for r in source_refs or []:
        sd = r.get("source_date") if isinstance(r, dict) else getattr(r, "source_date", None)
        d = _parse_src_date(sd)
        if d:
            dates.append(d)
    return max(dates) if dates else None


def _fields(post: Any, kw: Dict[str, Any]) -> Dict[str, Any]:
    if post is None:
        return kw
    if isinstance(post, dict):
        return {**post, **kw}
    # a Post action (or anything duck-typed like one)
    out = {k: getattr(post, k, None)
           for k in ("body_md", "title", "kind", "topic_tags", "expand_md", "source_refs")}
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

    freshest = _freshest_source_date(f.get("source_refs"))
    if freshest is not None:
        age = (date.today() - freshest).days
        if age > FRESH_DAYS and not _RECENCY_CONTEXT.search(text):
            warnings.append(
                f"freshest source is {freshest} (~{age // 30} mo old) and the body doesn't frame the recency — "
                "tie it to the current moment, or say it's older (ICYMI / \"back in <month>\"); "
                "don't present dated material as current (CRAFT 12)")

    if title:
        if kind in _LIGHT_KINDS:
            warnings.append(f"a {kind} takes no title — the body is the post")
        tw = title.split()
        if len(tw) > 16:
            warnings.append(f"title runs {len(tw)} words — state the finding, not the essay")
        if tw and (tw[-1].lower().rstrip(".,;:—") in _TITLE_DANGLERS or title.endswith((",", ";", ":", "—"))):
            warnings.append(f"title looks truncated mid-clause: {title!r}")

    return warnings
