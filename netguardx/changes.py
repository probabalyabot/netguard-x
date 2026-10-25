"""Apply proposed changes to a *copy* of a network (the counterfactual).

The input network is never modified.  Every applied change also yields its
inverse (used for rollback recommendations) and an ``Effect`` describing which
part of the configuration it touched (used for root-cause attribution).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .models import AclRule, Change, Link, Network, Policy, Route


class ChangeError(ValueError):
    """The change cannot be applied to this network (e.g. it edits a route that does not exist)."""


class Effect(BaseModel):
    index: int
    kind: str  # route | link | acl | policy
    nodes: list[str] = Field(default_factory=list)  # devices whose forwarding decisions may change
    prefix: Optional[str] = None
    policy_id: Optional[str] = None
    label: str = ""


def _find_routes(net: Network, router: str, prefix: str, next_hop: Optional[str]) -> list[int]:
    return [
        i for i, r in enumerate(net.routes)
        if r.router == router and r.destination == prefix and (next_hop is None or r.next_hop == next_hop)
    ]


def _require_node(net: Network, node_id: str, what: str) -> None:
    if node_id not in {n.id for n in net.nodes}:
        raise ChangeError(f"{what}: unknown device {node_id!r}")


def _apply_one(net: Network, ch: Change, index: int) -> tuple[Change, Effect]:
    op = ch.operation

    if op == "ADD_ROUTE":
        _require_node(net, ch.router, "ADD_ROUTE")
        if _find_routes(net, ch.router, ch.destination, ch.next_hop):
            raise ChangeError(f"{ch.router} already has route {ch.destination} via {ch.next_hop}")
        metric = 10 if ch.metric is None else ch.metric
        net.routes.append(Route(router=ch.router, destination=ch.destination, next_hop=ch.next_hop, metric=metric))
        inv = Change(operation="DELETE_ROUTE", router=ch.router, destination=ch.destination, next_hop=ch.next_hop)
        return inv, Effect(index=index, kind="route", nodes=[ch.router], prefix=ch.destination, label=ch.describe())

    if op in ("DELETE_ROUTE", "MODIFY_ROUTE", "CHANGE_METRIC"):
        _require_node(net, ch.router, op)
        selector = ch.old_next_hop if op == "MODIFY_ROUTE" else ch.next_hop
        found = _find_routes(net, ch.router, ch.destination, selector)
        if not found:
            raise ChangeError(f"{op}: {ch.router} has no route {ch.destination}" + (f" via {selector}" if selector else ""))
        if len(found) > 1:
            raise ChangeError(f"{op}: {ch.router} has several routes for {ch.destination}; say which next hop to edit")
        i = found[0]
        old = net.routes[i]
        eff = Effect(index=index, kind="route", nodes=[ch.router], prefix=ch.destination, label=ch.describe())
        if op == "DELETE_ROUTE":
            del net.routes[i]
            inv = Change(operation="ADD_ROUTE", router=old.router, destination=old.destination,
                         next_hop=old.next_hop, metric=old.metric)
        elif op == "MODIFY_ROUTE":
            net.routes[i] = Route(router=old.router, destination=old.destination, next_hop=ch.new_next_hop,
                                  metric=old.metric if ch.new_metric is None else ch.new_metric)
            inv = Change(operation="MODIFY_ROUTE", router=old.router, destination=old.destination,
                         old_next_hop=ch.new_next_hop, new_next_hop=old.next_hop, new_metric=old.metric)
        else:
            net.routes[i] = Route(router=old.router, destination=old.destination, next_hop=old.next_hop,
                                  metric=ch.new_metric)
            inv = Change(operation="CHANGE_METRIC", router=old.router, destination=old.destination,
                         next_hop=old.next_hop, new_metric=old.metric)
        return inv, eff

    if op in ("ADD_LINK", "DELETE_LINK"):
        _require_node(net, ch.node_a, op)
        _require_node(net, ch.node_b, op)
        pair = {ch.node_a, ch.node_b}
        existing = [i for i, l in enumerate(net.links) if {l.source, l.destination} == pair]
        eff = Effect(index=index, kind="link", nodes=[ch.node_a, ch.node_b], label=ch.describe())
        if op == "ADD_LINK":
            if existing or ch.node_a == ch.node_b:
                raise ChangeError(f"ADD_LINK: link {ch.node_a}-{ch.node_b} already exists or is invalid")
            cost = 1 if ch.cost is None else ch.cost
            net.links.append(Link(source=ch.node_a, destination=ch.node_b, cost=cost))
            return Change(operation="DELETE_LINK", node_a=ch.node_a, node_b=ch.node_b), eff
        if not existing:
            raise ChangeError(f"DELETE_LINK: no link between {ch.node_a} and {ch.node_b}")
        old = net.links.pop(existing[0])
        return Change(operation="ADD_LINK", node_a=old.source, node_b=old.destination, cost=old.cost), eff

    if op == "ADD_ACL_RULE":
        _require_node(net, ch.rule.node, op)
        rules_here = [i for i, a in enumerate(net.acls) if a.node == ch.rule.node]
        pos = len(rules_here) if ch.position is None else max(0, min(ch.position, len(rules_here)))
        insert_at = rules_here[pos] if pos < len(rules_here) else (rules_here[-1] + 1 if rules_here else len(net.acls))
        net.acls.insert(insert_at, ch.rule)
        inv = Change(operation="DELETE_ACL_RULE", node=ch.rule.node, rule_index=pos)
        return inv, Effect(index=index, kind="acl", nodes=[ch.rule.node], label=ch.describe())

    if op == "DELETE_ACL_RULE":
        node = ch.rule.node if ch.rule else ch.node
        _require_node(net, node, op)
        rules_here = [i for i, a in enumerate(net.acls) if a.node == node]
        if ch.rule is not None:
            matches = [k for k, i in enumerate(rules_here) if net.acls[i] == ch.rule]
            if not matches:
                raise ChangeError(f"DELETE_ACL_RULE: no matching rule on {node}")
            k = matches[0]
        else:
            k = ch.rule_index
            if k is None or not (0 <= k < len(rules_here)):
                raise ChangeError(f"DELETE_ACL_RULE: {node} has no rule_index {k} (it has {len(rules_here)} rules)")
        removed = net.acls.pop(rules_here[k])
        inv = Change(operation="ADD_ACL_RULE", rule=removed, position=k)
        return inv, Effect(index=index, kind="acl", nodes=[node], label=ch.describe())

    if op == "ADD_POLICY":
        known = {n.id for n in net.nodes}
        p = ch.policy.model_copy(deep=True)
        for end in (p.source, p.destination):
            if end not in known:
                raise ChangeError(f"ADD_POLICY: unknown device {end!r}")
        if p.waypoint and p.waypoint not in known:
            raise ChangeError(f"ADD_POLICY: unknown waypoint {p.waypoint!r}")
        used = {x.id for x in net.policies}
        if not p.id or p.id in used:
            n = len(net.policies) + 1
            while f"P{n}" in used:
                n += 1
            p.id = f"P{n}"
        net.policies.append(p)
        return Change(operation="DELETE_POLICY", policy_id=p.id), Effect(index=index, kind="policy", policy_id=p.id, label=ch.describe())

    if op == "DELETE_POLICY":
        idx = [i for i, p in enumerate(net.policies) if p.id == ch.policy_id]
        if not idx:
            raise ChangeError(f"DELETE_POLICY: no policy {ch.policy_id!r}")
        old = net.policies.pop(idx[0])
        return Change(operation="ADD_POLICY", policy=old), Effect(index=index, kind="policy", policy_id=old.id, label=ch.describe())

    raise ChangeError(f"unsupported operation {op}")


def apply_changes(network: Network, changes: list[Change],
                  share: bool = False) -> tuple[Network, list[Change], list[Effect]]:
    """Return (counterfactual network, inverse changes, effects). ``network`` is left untouched.

    With ``share=True`` the counterfactual reuses the input's device, route, link, ACL and policy
    objects instead of copying them, and is not re-validated.  That costs time proportional to the
    change rather than to the network, and suits callers that only read the result.
    """
    if share:
        cf = network.model_copy(update={f: list(getattr(network, f)) for f in ("links", "routes", "acls", "policies")})
    else:
        cf = network.model_copy(deep=True)
    inverses: list[Change] = []
    effects: list[Effect] = []
    for i, ch in enumerate(changes):
        inv, eff = _apply_one(cf, ch, i)
        inverses.append(inv)
        effects.append(eff)
    if share:
        return cf, inverses, effects
    # re-validate structure (dangling route next hops are allowed on purpose: that is a finding)
    try:
        cf = Network.model_validate(cf.model_dump())
    except ValueError as exc:
        raise ChangeError(f"the change produces an invalid network: {exc}") from exc
    return cf, inverses, effects
