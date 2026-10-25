"""Link changes: add or remove a cable between two devices.

    remove the link between R2 and FW        cable FW to BACKUP
    connect R2 and R3 with cost 5            disconnect R1 from R2
"""
from __future__ import annotations

import re
from typing import Optional

from . import routes
from .clauses import Clause
from .lexicon import Lexicon, number_after

_LINK_WORDS = re.compile(r"\blink\b|\bcable\b|\bconnection\b|\bdisconnect\b|\bconnect\s+\S+\s+(?:and|with)\s")
_DELETE = re.compile(r"\b(remove|delete|cut|drop|take down|decommission|disconnect|unplug)\b")
_ADD = re.compile(r"\b(add|create|connect|install|cable)\b")


def claims(low: str) -> bool:
    """A clause about a link that is not also about a route."""
    return bool(_LINK_WORDS.search(low)) and not routes.mentions_route(low)


def parse(clause: Clause, lex: Lexicon) -> tuple[Optional[dict], Optional[str]]:
    t = clause.text.strip()
    low = t.lower()
    nodes = lex.devices_in(t)
    if len(nodes) < 2:
        return None, lex.unknown_reason(t) or "could not find two devices for the link"
    a, b = nodes[0], nodes[1]
    if _DELETE.search(low):
        return {"operation": "DELETE_LINK", "node_a": a, "node_b": b}, None
    if _ADD.search(low):
        ch = {"operation": "ADD_LINK", "node_a": a, "node_b": b}
        cost = number_after(t, "cost")
        if cost is not None:
            ch["cost"] = cost
        return ch, None
    return None, "did not recognise the link operation"
