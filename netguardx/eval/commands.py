"""Synthetic command streams: a stand-in for an LLM agent, with a fixed seed.

Commands are drawn from the *initial* network, so the same stream can be replayed against several
gatekeeping strategies.  Each carries an ``intent`` naming the kind of edit it was generated as.
The intent is a category for reporting, not a safety label: whether a command is actually unsafe
is decided by the verifier against the state it is proposed in.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from ..models import AclRule, Change, Network

BENIGN = ("metric_tune", "redundant_route", "backup_link")
FAULTS = ("delete_route", "repoint_route", "delete_link", "shortcut_link", "open_acl", "block_acl")


class Command(BaseModel):
    step: int
    intent: str
    changes: list[Change]


def _unlinked_pair(rng: random.Random, left: list[str], right: list[str], adj: dict[str, set[str]]):
    for _ in range(20):
        a, b = rng.choice(left), rng.choice(right)
        if a != b and b not in adj[a]:
            return a, b
    return None


def _make(intent: str, net: Network, rng: random.Random, adj: dict[str, set[str]]) -> Optional[Change]:
    infra = [n.id for n in net.nodes if n.type in ("router", "firewall")]
    if intent == "metric_tune":
        r = rng.choice(net.routes)
        return Change(operation="CHANGE_METRIC", router=r.router, destination=r.destination,
                      next_hop=r.next_hop, new_metric=rng.randint(1, 200))
    if intent == "redundant_route":
        have = {(r.router, r.destination, r.next_hop) for r in net.routes}
        options = [(r, nb) for r in net.routes for nb in sorted(adj[r.router])
                   if nb != r.next_hop and (r.router, r.destination, nb) not in have]
        if not options:
            return None
        r, nb = rng.choice(options)
        return Change(operation="ADD_ROUTE", router=r.router, destination=r.destination, next_hop=nb,
                      metric=r.metric + rng.randint(50, 100))
    if intent == "delete_route":
        r = rng.choice(net.routes)
        return Change(operation="DELETE_ROUTE", router=r.router, destination=r.destination, next_hop=r.next_hop)
    if intent == "repoint_route":
        options = [r for r in net.routes if adj[r.router] - {r.next_hop}]
        if not options:
            return None
        r = rng.choice(options)
        return Change(operation="MODIFY_ROUTE", router=r.router, destination=r.destination,
                      old_next_hop=r.next_hop, new_next_hop=rng.choice(sorted(adj[r.router] - {r.next_hop})))
    if intent == "delete_link":
        l = rng.choice(net.links)
        return Change(operation="DELETE_LINK", node_a=l.source, node_b=l.destination)
    if intent in ("backup_link", "shortcut_link"):
        other = infra if intent == "backup_link" else [n.id for n in net.nodes if n.type == "server"]
        pair = _unlinked_pair(rng, infra, other, adj) if infra and other else None
        return Change(operation="ADD_LINK", node_a=pair[0], node_b=pair[1]) if pair else None
    if intent in ("open_acl", "block_acl"):
        firewalls = [n.id for n in net.nodes if n.type == "firewall"]
        if not firewalls:
            return None
        rule = AclRule(node=rng.choice(firewalls), action="ALLOW" if intent == "open_acl" else "DENY")
        return Change(operation="ADD_ACL_RULE", rule=rule, position=0)
    raise ValueError(f"unknown intent {intent!r}")


def generate_commands(network: Network, count: int, seed: int = 0, fault_rate: float = 0.3) -> list[Command]:
    """``count`` single-change commands; roughly ``fault_rate`` of them come from the fault classes."""
    if not network.routes or not network.links:
        raise ValueError("the network needs routes and links to generate commands from")
    rng = random.Random(seed)
    adj: dict[str, set[str]] = defaultdict(set)
    for l in network.links:
        adj[l.source].add(l.destination)
        adj[l.destination].add(l.source)
    out: list[Command] = []
    while len(out) < count:
        intent = rng.choice(FAULTS if rng.random() < fault_rate else BENIGN)
        change = _make(intent, network, rng, adj)
        if change is not None:  # this network offers nothing for that intent; draw again
            out.append(Command(step=len(out) + 1, intent=intent, changes=[change]))
    return out
