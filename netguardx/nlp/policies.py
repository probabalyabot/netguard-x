"""Reachability requirements ("APP must reach DB through FW"), drafted as policies, and deleting a
policy by its id ("delete policy P3")."""
from __future__ import annotations

import re
from typing import Any, Optional

from ..models import Network
from .lexicon import after, nodes_in

_DELETE = re.compile(r"\b(?:delete|remove|drop|retire)\s+(?:the\s+)?(?:policy|requirement)\s+#?([\w-]+)", re.I)


def claims_delete(low: str) -> bool:
    return bool(_DELETE.search(low))


def parse_delete(clause: str, net: Network) -> tuple[Optional[dict], Optional[str]]:
    wanted = _DELETE.search(clause).group(1)
    ids = {p.id.lower(): p.id for p in net.policies if p.id}
    if wanted.lower() in ids:
        return {"operation": "DELETE_POLICY", "policy_id": ids[wanted.lower()]}, None
    known = ", ".join(sorted(ids.values())) or "none"
    return None, f"no policy {wanted} (policies: {known})"


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
