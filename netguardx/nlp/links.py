"""Link changes: add or remove a cable between two devices."""
from __future__ import annotations

import re

from . import routes
from .lexicon import nodes_in

_LINK_WORDS = re.compile(r"\blink\b|\bcable\b|\bconnection\b")


def claims(low: str) -> bool:
    """A clause about a link that is not also about a route."""
    return bool(_LINK_WORDS.search(low)) and not routes.mentions_route(low)


def parse(t: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    low = t.lower()
    nodes = nodes_in(t, lookup)
    if len(nodes) < 2:
        return None, "could not find two devices for the link"
    if re.search(r"\b(remove|delete|cut|drop|take down|decommission|disconnect|unplug)\b", low):
        return {"operation": "DELETE_LINK", "node_a": nodes[0], "node_b": nodes[1]}, None
    if re.search(r"\b(add|create|connect|install|cable)\b", low):
        return {"operation": "ADD_LINK", "node_a": nodes[0], "node_b": nodes[1]}, None
    return None, "did not recognise the link operation"
