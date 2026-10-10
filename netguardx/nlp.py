"""Natural language -> structured intent (rule-based MVP).

This is the seam where an LLM belongs.  The contract is the same either way: free text goes in,
*structured, schema-validated* changes or policies come out, and a person reviews them before
the deterministic engine runs.  The model never decides whether a change is safe.

The rule-based parser below handles a small set of phrasings.  Anything it does not recognise
is returned in ``unparsed`` rather than guessed at.
"""
from __future__ import annotations

import re
from typing import Any

from .models import Network

_CIDR = r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?"


def _node_lookup(net: Network) -> dict[str, str]:
    m = {n.id.lower(): n.id for n in net.nodes}
    for n in net.nodes:
        if n.label:
            m.setdefault(n.label.lower(), n.id)
    internet = next((n.id for n in net.nodes if n.type == "internet"), None)
    if internet:
        m.setdefault("internet", internet)
        m.setdefault("the internet", internet)
    return m


def _nodes_in(text: str, lookup: dict[str, str]) -> list[str]:
    """Node ids in order of appearance."""
    found: list[tuple[int, str]] = []
    for name, nid in lookup.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I):
            found.append((m.start(), nid))
    found.sort()
    out: list[str] = []
    for _, nid in found:
        if nid not in out:
            out.append(nid)
    return out


def _after(text: str, words: str, lookup: dict[str, str], last: bool = False):
    names = "|".join(sorted((re.escape(k) for k in lookup), key=len, reverse=True))
    hits = re.findall(rf"\b(?:{words})\s+({names})(?![\w-])", text, re.I)
    if not hits:
        return None
    return lookup[(hits[-1] if last else hits[0]).lower()]


def _parse_change(clause: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    t = clause.strip()
    low = t.lower()
    prefix = re.search(_CIDR, t)
    is_route = "route" in low or bool(re.search(r"\b(send|forward|redirect|reroute)\b.*\b(traffic|packets)\b", low))
    is_link = bool(re.search(r"\blink\b|\bcable\b|\bconnection\b", low))

    if is_link and not is_route:
        nodes = _nodes_in(t, lookup)
        if len(nodes) < 2:
            return None, "could not find two devices for the link"
        if re.search(r"\b(remove|delete|cut|drop|take down|decommission|disconnect|unplug)\b", low):
            return {"operation": "DELETE_LINK", "node_a": nodes[0], "node_b": nodes[1]}, None
        if re.search(r"\b(add|create|connect|install|cable)\b", low):
            return {"operation": "ADD_LINK", "node_a": nodes[0], "node_b": nodes[1]}, None
        return None, "did not recognise the link operation"

    if is_route or "metric" in low:
        router = _after(t, "on|at|in", lookup)
        if not prefix or not router:
            return None, "a route change needs a device ('on R1') and a prefix ('10.0.5.0/24')"
        dest = prefix.group(0) if "/" in prefix.group(0) else prefix.group(0) + "/32"
        if "metric" in low:
            num = re.search(r"metric\D{0,12}(\d+)", low) or re.search(r"(\d+)\s*$", low)
            if not num:
                return None, "could not find the new metric"
            return {"operation": "CHANGE_METRIC", "router": router, "destination": dest,
                    "new_metric": int(num.group(1))}, None
        nh = _after(t, "via|through|use|using|next[- ]hop(?: to| of| is)?|to", lookup, last=True)
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
    return None, "not a route or link change"


def _parse_policy(clause: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    t = clause.strip()
    if not re.search(r"\b(reach|access|connect to|talk to|communicate with)\b", t, re.I):
        return None, "not a reachability requirement"
    nodes = _nodes_in(t, lookup)
    if len(nodes) < 2:
        return None, "could not find two devices"
    deny = bool(re.search(r"\bnever\b|\bnot\b|n't\b|\bcannot\b|\bno access\b|\bforbid|\bblock", t, re.I))
    # order of appearance decides source/destination
    src, dst = nodes[0], nodes[1]
    port = re.search(r"(?:port|tcp|udp)\s*[/:]?\s*(\d{1,5})", t, re.I)
    proto = re.search(r"\b(tcp|udp|icmp)\b", t, re.I)
    pol: dict[str, Any] = {
        "action": "DENY" if deny else "ALLOW", "source": src, "destination": dst,
        "protocol": proto.group(1).upper() if proto else "TCP",
    }
    if port:
        pol["port"] = int(port.group(1))
    wp = _after(t, "through|via|across", lookup)
    if wp and wp not in (src, dst) and not deny:
        pol["waypoint"] = wp
    return pol, None


def interpret(text: str, net: Network) -> dict[str, Any]:
    lookup = _node_lookup(net)
    clauses = [c for c in re.split(r"\.(?=\s|$)|[;\n]|,\s*(?:but\s+|and\s+)?|\s+but\s+", text) if c and c.strip()]
    changes: list[dict] = []
    policies: list[dict] = []
    unparsed: list[dict] = []
    for clause in clauses:
        ch, why_c = _parse_change(clause, lookup)
        if ch:
            changes.append(ch)
            continue
        pol, why_p = _parse_policy(clause, lookup)
        if pol:
            policies.append(pol)
            continue
        unparsed.append({"text": clause.strip(), "reason": why_c if why_c != "not a route or link change" else why_p})
    kind = "changes" if changes and not policies else "requirements" if policies and not changes else \
        "mixed" if changes and policies else "unknown"
    return {
        "parser": "rule-based",
        "kind": kind,
        "changes": changes,
        "policies": policies,
        "unparsed": unparsed,
        "needs_review": True,
        "note": "Review the structured result before analysing. This parser only understands simple "
                "route, link and reachability phrasings.",
    }
