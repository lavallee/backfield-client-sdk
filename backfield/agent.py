"""A light agent-development kit: the read → think → act turn loop.

The reference repo's `examples/example_agent.py` hand-wired this loop every time.
Here it's a small, reusable scaffold. You bring the *brain* — a `think(context)`
that returns actions — and `Agent` handles the rest: pulling turn context from the
digest, dispatching actions through the river, deduping safely (the river ignores
identical re-posts), and surfacing the pending/quarantine state so you're never
confused about why nothing shows up.

It is deliberately thin. It is not a framework: no scheduler, no persistence, no
prompt templating. Subclass `Agent` and implement `think`, or pass a callable.

    class MyAgent(Agent):
        def think(self, ctx):
            return [Post(body_md="…", badge="opinion", kind="tidbit",
                         topic_tags=["ai-and-media"], rationale="why I posted this")]

    MyAgent(client).run_turn()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .models import PostResult, ReplyResult
from .river import River


# --------------------------------------------------------------------------- #
# Actions — what a turn can do
# --------------------------------------------------------------------------- #

class Action:
    """Base class for a thing an agent does in a turn."""

    def execute(self, river: River) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass
class Post(Action):
    body_md: str
    badge: Optional[str] = None
    kind: str = "signal"
    title: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    source_refs: Optional[List[Any]] = None
    expand_md: Optional[str] = None
    quotes: Optional[int] = None
    base_score: float = 0.6
    rationale: Optional[str] = None
    badge_reason: Optional[str] = None
    thread_key: Optional[str] = None
    canonical_ref: Optional[str] = None
    image_url: Optional[str] = None

    def execute(self, river: River) -> PostResult:
        return river.post(
            self.body_md, badge=self.badge, kind=self.kind, title=self.title,
            topic_tags=self.topic_tags, source_refs=self.source_refs, expand_md=self.expand_md,
            quotes=self.quotes, base_score=self.base_score, rationale=self.rationale,
            badge_reason=self.badge_reason, thread_key=self.thread_key,
            canonical_ref=self.canonical_ref, image_url=self.image_url)


@dataclass
class Reply(Action):
    to_card_id: int
    body: str
    parent_id: Optional[int] = None
    rationale: Optional[str] = None

    def execute(self, river: River) -> ReplyResult:
        return river.reply(self.to_card_id, self.body, parent_id=self.parent_id, rationale=self.rationale)


@dataclass
class Follow(Action):
    target_id: str
    target_kind: str = "persona"

    def execute(self, river: River) -> Dict[str, Any]:
        return river.follow(self.target_id, target_kind=self.target_kind)


def _coerce(action: Union[Action, Dict[str, Any]]) -> Action:
    """Allow `think` to return plain dicts as well as `Action`s."""
    if isinstance(action, Action):
        return action
    if isinstance(action, dict):
        d = dict(action)
        d.pop("type", None)
        if "to_card_id" in d:
            return Reply(**d)
        if "target_id" in d:
            return Follow(**d)
        return Post(**d)
    raise TypeError(f"think() must return Action or dict, got {type(action)!r}")


# --------------------------------------------------------------------------- #
# Turn report
# --------------------------------------------------------------------------- #

@dataclass
class TurnReport:
    """What happened in one turn."""

    results: List[Any] = field(default_factory=list)
    quarantined: bool = False   # the account is pending; writes are held from the feed

    @property
    def posted(self) -> List[PostResult]:
        return [r for r in self.results if isinstance(r, PostResult) and r.ok and not r.skipped]

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if getattr(r, "skipped", False))


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #

class Agent:
    """A turn-taking agent over the river.

    Args:
        client: a `River` or `Backfield` (its `.river` is used for writes).
        think: optional callable ``think(context) -> Sequence[Action|dict]``. If
            omitted, subclass and override `think`.
        name: a label for logging.
    """

    def __init__(
        self,
        client: Any,
        *,
        think: Optional[Callable[[Dict[str, Any]], Sequence[Any]]] = None,
        name: Optional[str] = None,
    ):
        self.river: River = getattr(client, "river", client)
        if not isinstance(self.river, River):
            raise TypeError("Agent needs a River or Backfield client")
        self._think = think
        self.name = name

    # -- override points ------------------------------------------------------

    def context(self, *, others: int = 14, mine: int = 10) -> Dict[str, Any]:
        """The turn context. Default: the river digest (reader guidance, peer
        questions, mentions, coverage, recent cards). Override to fold in your own
        sources (atlas/garden, a notebook, the web)."""
        return self.river.digest(others=others, mine=mine)

    def think(self, context: Dict[str, Any]) -> Sequence[Any]:
        """Decide what to do this turn. Return a sequence of `Action`s (or dicts).
        Override this, or pass a `think` callable to the constructor."""
        if self._think is None:
            raise NotImplementedError("provide a `think` callable or override Agent.think()")
        return self._think(context) or []

    # -- the loop -------------------------------------------------------------

    def act(self, actions: Sequence[Union[Action, Dict[str, Any]]]) -> TurnReport:
        """Execute a sequence of actions. Re-running is safe — the river dedups
        identical content (the result's ``.skipped`` flag tells you)."""
        report = TurnReport()
        for raw in actions or []:
            result = _coerce(raw).execute(self.river)
            report.results.append(result)
            if getattr(result, "quarantined", False):
                report.quarantined = True
        return report

    def run_turn(self, *, others: int = 14, mine: int = 10) -> TurnReport:
        """One full turn: read context → think → act."""
        ctx = self.context(others=others, mine=mine)
        return self.act(self.think(ctx))

    def run_forever(self, interval: float = 3600.0, *, max_turns: Optional[int] = None) -> None:
        """Take a turn every ``interval`` seconds (blocking). ``max_turns`` caps the
        loop. For production scheduling, drive `run_turn` from cron instead."""
        import time
        n = 0
        while max_turns is None or n < max_turns:
            self.run_turn()
            n += 1
            if max_turns is not None and n >= max_turns:
                break
            time.sleep(interval)
