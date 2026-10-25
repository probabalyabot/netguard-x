"""Route changes: add, delete, modify (new next hop) and metric, in plain English or Cisco style.

Plain English names the router ("on R1", "R1's"), a destination and, for add / modify, a next hop:

    change the route on R1 for 10.0.5.0/24 to R3       send DB traffic on R1 via R3
    add a route on R1 to 10.0.7.0/24 via R3 with metric 20
    remove the default route on R1                      set the metric of R1's default route to 50
    point R2 at R1 for 10.0.5.0/24                      change R1's route for DB from R2 to R3

The destination is a prefix (CIDR, address + netmask, or an address), "the default route", or a
device: then it is the router's existing route that covers that device ("DB traffic" on R1 is
R1's 10.0.5.0/24 route).  Only a specific route is used that way; when the default route is the
only one covering the device, the parser asks for the prefix instead of quietly editing the
default route.

Cisco style, with the router taken from a header line (``R1(config)#``) or "on R1":

    ip route 10.0.7.0 255.255.255.0 R3 [20]            no ip route 0.0.0.0 0.0.0.0 INET

``ip route`` adds a route (a second one, if the prefix already has a route via another next hop,
just as a router would); to replace a next hop, say "change ... to ...".  The optional number after
the next hop is taken as the metric.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .clauses import Clause
from .lexicon import LexError, Lexicon, number_after, prefix_span

_CISCO = re.compile(r"^\s*(no\s+)?ip\s+route\s+(.*)$", re.I)
_POINT = re.compile(r"\bpoint\s+(\S+)\s+(?:at|to)\s+(\S+)", re.I)
_FROM_TO = re.compile(r"\bfrom\s+(\S+)\s+to\s+(\S+)", re.I)
_POSSESSIVE = re.compile(r"([A-Za-z0-9_.-]+)'s\b")
_TRAFFIC_OF = re.compile(r"([A-Za-z0-9_.-]+)\s+(?:traffic|packets)\b", re.I)

NEXT_HOP = r"via|through|use|using|next[- ]hop(?: to| of| is)?"
_DELETE = re.compile(r"\b(delete|remove|drop|withdraw)\b")
_ADD = re.compile(r"\b(add|create|new|install)\b")
_CHANGE = re.compile(r"\b(change|modify|set|update|move|point|redirect|switch|reroute|send|forward)\b|^\s*route\b")
_MISSING_DESTINATION = ("a route change needs a destination: a prefix ('10.0.5.0/24'), "
                        "'the default route', or a device ('DB traffic')")

Result = tuple[Optional[dict], Optional[str]]


def mentions_route(low: str) -> bool:
    return "route" in low or bool(re.search(r"\b(send|forward|redirect|reroute)\b.*\b(traffic|packets)\b", low))


def claims(low: str) -> bool:
    return mentions_route(low) or "metric" in low or bool(re.search(r"\bpoint\s+\S+\s+(?:at|to)\b", low))


def parse(clause: Clause, lex: Lexicon) -> Result:
    t = clause.text.strip()
    try:
        m = _CISCO.match(t)
        ch, why = _cisco(bool(m.group(1)), m.group(2), clause, lex) if m else _english(t, clause, lex)
    except LexError as exc:
        ch, why = None, str(exc)
    if ch is None:
        why = lex.unknown_reason(t) or why
    return ch, why


def _english(t: str, clause: Clause, lex: Lexicon) -> Result:
    low = t.lower()
    router = next_hop = old_next_hop = None
    point = _POINT.search(t)
    if point and lex.device(point.group(1)) and lex.device(point.group(2)):
        router, next_hop = lex.device(point.group(1)), lex.device(point.group(2))
    moved = _FROM_TO.search(t)
    if moved and lex.device(moved.group(1)) and lex.device(moved.group(2)):
        old_next_hop, next_hop = lex.device(moved.group(1)), lex.device(moved.group(2))
    router = router or lex.after(t, "on|at|in") or _possessive(t, lex) or clause.device
    if router is None:
        return None, "a route change needs a device ('on R1')"

    span = prefix_span(t)
    prefix = span[0] if span else ("0.0.0.0/0" if re.search(r"\bdefault route\b", low) else None)
    if next_hop is None:
        next_hop = lex.after(t, NEXT_HOP, last=True)
    deleting = bool(_DELETE.search(low))
    target = None
    if prefix is None:
        target = lex.after(t, "for") or _traffic_of(t, lex)
        # "to DB" names the destination only when the next hop is named otherwise ("via R3"), or
        # when there is none to name (a delete); in "change the route on R1 to R3" it is the next hop
        if target is None and (next_hop or deleting):
            target = lex.after(t, "to")
        if target in (router, next_hop):
            target = None
    if next_hop is None:  # "... to R3" names the next hop when "to" does not name the destination
        to = lex.after(t, "to", last=True)
        next_hop = to if to not in (router, target) else None

    adding = bool(_ADD.search(low)) and next_hop is not None
    if prefix is None:
        if target is None:
            return None, _MISSING_DESTINATION
        prefix, why = _route_for(router, target, lex, adding)
        if prefix is None:
            return None, why

    if deleting:
        ch: dict[str, Any] = {"operation": "DELETE_ROUTE", "router": router, "destination": prefix}
        if next_hop:
            ch["next_hop"] = next_hop
        return ch, None
    if adding:
        ch = {"operation": "ADD_ROUTE", "router": router, "destination": prefix, "next_hop": next_hop}
        metric = number_after(t, "metric")
        if metric is not None:
            ch["metric"] = metric
        return ch, None
    if "metric" in low:
        metric = number_after(t, "metric") or _trailing_number(t)
        if metric is None:
            return None, "could not find the new metric"
        ch = {"operation": "CHANGE_METRIC", "router": router, "destination": prefix, "new_metric": metric}
        if next_hop:
            ch["next_hop"] = next_hop
        return ch, None
    if next_hop is None:
        return None, "could not find the next hop ('via R3')"
    if _CHANGE.search(low):
        ch = {"operation": "MODIFY_ROUTE", "router": router, "destination": prefix, "new_next_hop": next_hop}
        if old_next_hop:
            ch["old_next_hop"] = old_next_hop
        return ch, None
    return None, "did not recognise the route operation"


def _cisco(negated: bool, args: str, clause: Clause, lex: Lexicon) -> Result:
    router = clause.device or lex.after(args, "on")
    if router is None:
        return None, "a Cisco line needs a device: start with 'R1(config)#' or put 'on R1:' in front"
    span = prefix_span(args)
    if span is None:
        return None, "ip route needs a destination: an address and netmask ('10.0.5.0 255.255.255.0')"
    prefix, _, end = span
    rest = [w for w in args[end:].split() if w.lower() != "on" and lex.device(w) != router]
    next_hop = lex.device(rest[0]) if rest else None
    if rest and next_hop is None:
        return None, f"unknown next hop {rest[0]}"
    if negated:
        ch: dict[str, Any] = {"operation": "DELETE_ROUTE", "router": router, "destination": prefix}
        if next_hop:
            ch["next_hop"] = next_hop
        return ch, None
    if next_hop is None:
        return None, "ip route needs a next hop after the destination ('... 255.255.255.0 R3')"
    ch = {"operation": "ADD_ROUTE", "router": router, "destination": prefix, "next_hop": next_hop}
    if len(rest) > 1 and rest[1].isdigit():
        ch["metric"] = int(rest[1])
    return ch, None


def _route_for(router: str, device: str, lex: Lexicon, adding: bool) -> tuple[Optional[str], Optional[str]]:
    """The prefix meant by "<device> traffic" on ``router``: its most specific static route covering
    the device, never the default route.  A new route with no existing one to follow is a /32."""
    covering = lex.route_covering(router, device)
    if covering and covering != "0.0.0.0/0":
        return covering, None
    if adding:
        node = next(n for n in lex.net.nodes if n.id == device)
        if node.ip:
            return f"{node.ip}/32", None
    where = "only the default route covers it" if covering else "it has no route covering it"
    return None, f"{router} has no specific route for {device} ({where}); give the prefix, e.g. 10.0.5.0/24"


def _possessive(t: str, lex: Lexicon) -> Optional[str]:
    for m in _POSSESSIVE.finditer(t):
        if (dev := lex.device(m.group(1))):
            return dev
    return None


def _traffic_of(t: str, lex: Lexicon) -> Optional[str]:
    m = _TRAFFIC_OF.search(t)
    return lex.device(m.group(1)) if m else None


def _trailing_number(t: str) -> Optional[int]:
    m = re.search(r"(?<![\w.])(\d+)\s*$", t)
    return int(m.group(1)) if m else None
