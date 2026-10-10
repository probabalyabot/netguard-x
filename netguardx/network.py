"""Deterministic forwarding simulation.

``NetworkState`` indexes a ``Network`` for fast lookups.  ``simulate`` walks a
packet hop by hop: ACL check on ingress, then longest-prefix-match route
lookup, then the next device.  Forwarding is destination-based, so visiting a
device twice means a forwarding loop.

Scope of the MVP: IPv4/IPv6 static routing only, one-way traffic (return paths
are not simulated), undirected links, no NAT, no dynamic routing protocols.
"""
from __future__ import annotations

import ipaddress
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from .models import AclRule, Network, norm_protocol, traffic_key

DELIVERED = "DELIVERED"
DROPPED_ACL = "DROPPED_ACL"
LOOP = "LOOP"
BLACKHOLE = "BLACKHOLE"
INVALID_NEXT_HOP = "INVALID_NEXT_HOP"
ROUTING_FAILURES = {LOOP, BLACKHOLE, INVALID_NEXT_HOP}


@dataclass(frozen=True)
class RouteEntry:
    prefix: ipaddress.IPv4Network | ipaddress.IPv6Network
    next_hop: str
    metric: int
    origin: str  # "static" or "connected"


class HopRoute(BaseModel):
    prefix: str
    next_hop: str
    metric: int
    origin: str


class AclDecision(BaseModel):
    node: str
    action: str
    rule_index: Optional[int] = None  # None means the node's default action applied
    rule: str


class Hop(BaseModel):
    node: str
    acl: Optional[AclDecision] = None
    route: Optional[HopRoute] = None


class Trace(BaseModel):
    key: str
    source: str
    destination: str
    protocol: str
    port: Optional[int]
    status: str
    path: list[str]
    hops: list[Hop]
    stop_node: Optional[str] = None
    detail: str = ""

    @property
    def delivered(self) -> bool:
        return self.status == DELIVERED


class NetworkState:
    def __init__(self, net: Network):
        self.net = net
        self.nodes = {n.id: n for n in net.nodes}
        self.adj: dict[str, dict[str, int]] = defaultdict(dict)
        for l in net.links:
            self.adj[l.source][l.destination] = l.cost
            self.adj[l.destination][l.source] = l.cost

        self.owned: dict[str, set] = {
            n.id: {ipaddress.ip_address(a) for a in n.ip_addresses} for n in net.nodes
        }
        self.routes: dict[str, list[RouteEntry]] = defaultdict(list)
        for r in net.routes:
            self.routes[r.router].append(
                RouteEntry(ipaddress.ip_network(r.destination), r.next_hop, r.metric, "static")
            )
        # directly attached devices are reachable without a configured route
        for node_id, neighbours in self.adj.items():
            for nb in neighbours:
                for ip in self.nodes[nb].ip_addresses:
                    self.routes[node_id].append(
                        RouteEntry(ipaddress.ip_network(ip), nb, 0, "connected")
                    )
        self.acls: dict[str, list[AclRule]] = defaultdict(list)
        for a in net.acls:
            self.acls[a.node].append(a)

    def derive(self, net: Network, touched: set[str]) -> "NetworkState":
        """State for ``net``, which differs from this state's network only in the routes, ACL rules
        and links of the ``touched`` devices.  Their tables are rebuilt; all others are shared."""
        new = object.__new__(NetworkState)
        new.net, new.nodes, new.owned = net, self.nodes, self.owned
        new.adj, new.routes, new.acls = dict(self.adj), dict(self.routes), dict(self.acls)
        for t in touched:
            new.adj[t], new.routes[t], new.acls[t] = {}, [], []
        for l in net.links:
            if l.source in touched:
                new.adj[l.source][l.destination] = l.cost
            if l.destination in touched:
                new.adj[l.destination][l.source] = l.cost
        for r in net.routes:
            if r.router in touched:
                new.routes[r.router].append(
                    RouteEntry(ipaddress.ip_network(r.destination), r.next_hop, r.metric, "static")
                )
        for t in touched:
            for nb in new.adj[t]:
                for ip in self.nodes[nb].ip_addresses:
                    new.routes[t].append(RouteEntry(ipaddress.ip_network(ip), nb, 0, "connected"))
        for a in net.acls:
            if a.node in touched:
                new.acls[a.node].append(a)
        return new

    # ------------------------------------------------------------------ lookups
    def primary_ip(self, node_id: str) -> Optional[str]:
        n = self.nodes.get(node_id)
        return n.ip if n else None

    def lookup(self, node_id: str, dst_ip) -> Optional[RouteEntry]:
        """Longest prefix match; ties broken by lowest metric, then next-hop name."""
        best: Optional[RouteEntry] = None
        best_key = None
        for e in self.routes.get(node_id, ()):
            if dst_ip in e.prefix:
                k = (-e.prefix.prefixlen, e.metric, e.next_hop)
                if best_key is None or k < best_key:
                    best, best_key = e, k
        return best

    # --------------------------------------------------------------------- ACLs
    def _endpoint_match(self, spec: str, node_id: str) -> bool:
        s = (spec or "any").strip()
        if s.lower() in ("any", "*"):
            return True
        if s == node_id:
            return True
        ip = self.primary_ip(node_id)
        if ip is None:
            return False
        try:
            if "/" in s:
                return ipaddress.ip_address(ip) in ipaddress.ip_network(s, strict=False)
            return ipaddress.ip_address(ip) == ipaddress.ip_address(s)
        except ValueError:
            return False

    def _rule_matches(self, r: AclRule, source: str, destination: str, protocol: str, port) -> bool:
        if not self._endpoint_match(r.source, source):
            return False
        if not self._endpoint_match(r.destination, destination):
            return False
        if r.protocol != "ANY" and r.protocol != norm_protocol(protocol):
            return False
        if r.port is not None and r.port != port:
            return False
        return True

    def acl_decision(self, node_id: str, source: str, destination: str, protocol: str, port) -> Optional[AclDecision]:
        rules = self.acls.get(node_id, [])
        for i, r in enumerate(rules):
            if self._rule_matches(r, source, destination, protocol, port):
                return AclDecision(node=node_id, action=r.action, rule_index=i, rule=r.describe())
        default = self.nodes[node_id].effective_default_action
        if rules or default == "DENY":
            return AclDecision(node=node_id, action=default, rule_index=None, rule=f"default {default}")
        return None


def simulate(state: NetworkState, source: str, destination: str, protocol: str, port: Optional[int]) -> Trace:
    key = traffic_key(source, destination, protocol, port)
    proto = norm_protocol(protocol)

    def done(status, path, hops, stop, detail):
        return Trace(
            key=key, source=source, destination=destination, protocol=proto, port=port,
            status=status, path=path, hops=hops, stop_node=stop, detail=detail,
        )

    dst_ip_s = state.primary_ip(destination)
    if source not in state.nodes or destination not in state.nodes:
        return done(BLACKHOLE, [source], [], source, "unknown source or destination device")
    if dst_ip_s is None:
        return done(BLACKHOLE, [source], [Hop(node=source)], source, f"{destination} has no IP address")
    dst_ip = ipaddress.ip_address(dst_ip_s)

    path = [source]
    hops: list[Hop] = []
    visited = {source}
    cur = source
    first = True
    while True:
        hop = Hop(node=cur)
        hops.append(hop)
        if not first:
            acl = state.acl_decision(cur, source, destination, proto, port)
            if acl is not None:
                hop.acl = acl
                if acl.action == "DENY":
                    return done(DROPPED_ACL, path, hops, cur, f"{cur} drops the traffic ({acl.rule})")
        first = False
        if dst_ip in state.owned[cur]:
            return done(DELIVERED, path, hops, cur, f"delivered to {cur}")
        entry = state.lookup(cur, dst_ip)
        if entry is None:
            return done(BLACKHOLE, path, hops, cur, f"{cur} has no route to {dst_ip_s}")
        hop.route = HopRoute(
            prefix=str(entry.prefix), next_hop=entry.next_hop, metric=entry.metric, origin=entry.origin
        )
        nh = entry.next_hop
        if nh not in state.nodes:
            return done(INVALID_NEXT_HOP, path, hops, cur,
                        f"{cur} forwards {entry.prefix} to {nh}, which is not a device in the network")
        if nh not in state.adj.get(cur, {}):
            return done(INVALID_NEXT_HOP, path, hops, cur,
                        f"{cur} forwards {entry.prefix} to {nh}, but there is no link {cur}-{nh}")
        path.append(nh)
        if nh in visited:
            return done(LOOP, path, hops, nh, "forwarding loop: " + " -> ".join(path))
        visited.add(nh)
        cur = nh


@dataclass
class StaticIssue:
    kind: str
    node: str
    prefix: str
    next_hop: str
    message: str

    def key(self) -> tuple:
        return (self.kind, self.node, self.prefix, self.next_hop)


def static_issues(state: NetworkState) -> list[StaticIssue]:
    """Route-table lint: routes whose next hop cannot be used."""
    out: list[StaticIssue] = []
    for r in state.net.routes:
        if r.next_hop not in state.nodes:
            out.append(StaticIssue("UNKNOWN_NEXT_HOP", r.router, r.destination, r.next_hop,
                                   f"{r.router}: route {r.destination} points at unknown device {r.next_hop}"))
        elif r.next_hop not in state.adj.get(r.router, {}):
            out.append(StaticIssue("UNLINKED_NEXT_HOP", r.router, r.destination, r.next_hop,
                                   f"{r.router}: route {r.destination} via {r.next_hop}, but there is no link {r.router}-{r.next_hop}"))
    return out
