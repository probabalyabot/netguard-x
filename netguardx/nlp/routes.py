"""Route changes: add, delete, modify (new next hop) and metric."""
from __future__ import annotations

import re
from typing import Any

from .lexicon import CIDR, after


def mentions_route(low: str) -> bool:
    return "route" in low or bool(re.search(r"\b(send|forward|redirect|reroute)\b.*\b(traffic|packets)\b", low))


def claims(low: str) -> bool:
    return mentions_route(low) or "metric" in low


def parse(t: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    low = t.lower()
    prefix = re.search(CIDR, t)
    router = after(t, "on|at|in", lookup)
    if not prefix or not router:
        return None, "a route change needs a device ('on R1') and a prefix ('10.0.5.0/24')"
    dest = prefix.group(0) if "/" in prefix.group(0) else prefix.group(0) + "/32"
    if "metric" in low:
        num = re.search(r"metric\D{0,12}(\d+)", low) or re.search(r"(\d+)\s*$", low)
        if not num:
            return None, "could not find the new metric"
        return {"operation": "CHANGE_METRIC", "router": router, "destination": dest,
                "new_metric": int(num.group(1))}, None
    nh = after(t, "via|through|use|using|next[- ]hop(?: to| of| is)?|to", lookup, last=True)
    if re.search(r"\b(delete|remove|drop)\b", low):
        ch: dict[str, Any] = {"operation": "DELETE_ROUTE", "router": router, "destination": dest}
        if nh:
            ch["next_hop"] = nh
        return ch, None
    if not nh:
        return None, "could not find the next hop ('via R3')"
    if re.search(r"\b(add|create|new)\b", low):
        return {"operation": "ADD_ROUTE", "router": router, "destination": dest, "next_hop": nh}, None
    if re.search(r"\b(change|modify|set|update|move|point|redirect|switch|reroute|send|forward)\b", low):
        return {"operation": "MODIFY_ROUTE", "router": router, "destination": dest, "new_next_hop": nh}, None
    return None, "did not recognise the route operation"
