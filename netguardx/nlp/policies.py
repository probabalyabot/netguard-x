"""Reachability requirements ("APP must reach DB through FW"), drafted as policies."""
from __future__ import annotations

import re
from typing import Any

from .lexicon import after, nodes_in


def parse(clause: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    t = clause.strip()
    if not re.search(r"\b(reach|access|connect to|talk to|communicate with)\b", t, re.I):
        return None, "not a reachability requirement"
    nodes = nodes_in(t, lookup)
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
    wp = after(t, "through|via|across", lookup)
    if wp and wp not in (src, dst) and not deny:
        pol["waypoint"] = wp
    return pol, None
