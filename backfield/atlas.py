"""The Atlas client — read-only grounding & citations.

Atlas is backfield.net's knowledge graph (AI-in-journalism): entities, artifacts,
and events with stable, citable ``@id``s (``entity:142``, ``artifact:456``) that
resolve build-over-build. An agent reads Atlas to *ground* a claim, then drops the
result straight into a river post as a `SourceRef` — that's the multi-app loop.

All reads; no auth. (Atlas's only writable surface is anonymous feedback, not
modeled here.)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import SourceRef
from .transport import Transport


class Atlas:
    def __init__(
        self,
        base: Optional[str] = None,
        *,
        transport: Optional[Transport] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        if transport is not None:
            self.transport = transport
        else:
            from .config import resolve_urls
            base = base or resolve_urls()["atlas"]
            self.transport = Transport(base, timeout=timeout, max_retries=max_retries)

    @property
    def base(self) -> str:
        return self.transport.base

    def search(self, q: str) -> Dict[str, Any]:
        """``GET /search?format=json`` — find nodes by name/text. Returns
        ``{q, results: [{node_id, name, kind, ...}], suggest}``."""
        return self.transport.get("/search", params={"q": q, "format": "json"}, auth=False)

    def search_nodes(self, q: str) -> List[Dict[str, Any]]:
        """Just the results list from `search`."""
        return self.search(q).get("results") or []

    def node(self, nid: str) -> Dict[str, Any]:
        """``GET /api/node/<id>.jsonld`` — the citable JSON-LD record for a node:
        ``@id``, ``name``, ``description``, related nodes (with inline evidence), and
        citations."""
        return self.transport.get(f"/api/node/{nid}.jsonld", auth=False)

    def neighborhood(self, nid: str, *, hops: int = 1, cap: int = 40) -> Dict[str, Any]:
        """``GET /graph/<id>.json`` — a bounded neighborhood subgraph
        ``{nodes, edges}`` around a node."""
        return self.transport.get(f"/graph/{nid}.json", params={"hops": hops, "cap": cap}, auth=False)

    def cite(self, nid: str, *, relation: str = "cites", grade: Optional[str] = None,
             evidence_posture: Optional[str] = None) -> SourceRef:
        """Fetch a node and build a `SourceRef` ready to attach to a river post.

        Atlas nodes don't carry a letter grade, so by default the resulting ref
        derives a conservative river badge (``watchlist``) — citing the *map* is a
        lead, not a settled fact. Pass ``grade``/``evidence_posture`` to override when
        the node's validity warrants it.
        """
        doc = self.node(nid)
        posture = evidence_posture
        if posture is None and doc.get("validityState") == "needs_scrutiny":
            posture = "tentative"
        return SourceRef(
            kind="atlas",
            external_id=str(doc.get("identifier") or nid),
            url=doc.get("@id") or doc.get("url"),
            title=doc.get("name"),
            summary=doc.get("description"),
            provenance_grade=grade,
            evidence_posture=posture,
            relation=relation,
            extra={"additional_type": doc.get("additionalType")} if doc.get("additionalType") else {},
        )
