"""Vocabulary shared by the grammar modules: device names and address patterns."""
from __future__ import annotations

import re

from ..models import Network

CIDR = r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?"


def node_lookup(net: Network) -> dict[str, str]:
    """Lower-cased names a device can be called by (id, label, "internet") -> device id."""
    m = {n.id.lower(): n.id for n in net.nodes}
    for n in net.nodes:
        if n.label:
            m.setdefault(n.label.lower(), n.id)
    internet = next((n.id for n in net.nodes if n.type == "internet"), None)
    if internet:
        m.setdefault("internet", internet)
        m.setdefault("the internet", internet)
    return m


def nodes_in(text: str, lookup: dict[str, str]) -> list[str]:
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


def after(text: str, words: str, lookup: dict[str, str], last: bool = False):
    """The device named right after one of ``words`` (a regex alternation), first or last occurrence."""
    names = "|".join(sorted((re.escape(k) for k in lookup), key=len, reverse=True))
    hits = re.findall(rf"\b(?:{words})\s+({names})(?![\w-])", text, re.I)
    if not hits:
        return None
    return lookup[(hits[-1] if last else hits[0]).lower()]
