"""Data model for NetGuard-X.

A ``Network`` is a plain, serialisable description of devices, links, static
routes, ACLs, important traffic flows and security policies.  A ``Change`` is
one proposed edit to that description.  Nothing in here mutates a live network.
"""
from __future__ import annotations

import ipaddress
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

NodeType = Literal["router", "firewall", "host", "server", "internet"]
Action = Literal["ALLOW", "DENY"]
ENDPOINT_TYPES = {"host", "server", "internet"}

Operation = Literal[
    "ADD_ROUTE",
    "DELETE_ROUTE",
    "MODIFY_ROUTE",
    "CHANGE_METRIC",
    "ADD_LINK",
    "DELETE_LINK",
    "ADD_ACL_RULE",
    "DELETE_ACL_RULE",
    "ADD_POLICY",
    "DELETE_POLICY",
]


def norm_protocol(value: Optional[str]) -> str:
    if value is None:
        return "ANY"
    v = str(value).strip().upper()
    return "ANY" if v in ("", "*", "ANY") else v


def norm_prefix(value: str) -> str:
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError as exc:
        raise ValueError(f"invalid prefix {value!r}") from exc


def traffic_key(source: str, destination: str, protocol: str, port: Optional[int]) -> str:
    return f"{source}>{destination}/{norm_protocol(protocol)}/{port if port is not None else '*'}"


class Node(BaseModel):
    id: str
    type: NodeType = "host"
    ip_addresses: list[str] = Field(default_factory=list)
    default_action: Optional[Action] = None  # what an ACL-bearing node does when no rule matches
    criticality: int = Field(1, ge=1, le=5)
    label: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None

    @field_validator("ip_addresses")
    @classmethod
    def _check_ips(cls, v: list[str]) -> list[str]:
        out = []
        for a in v:
            try:
                out.append(str(ipaddress.ip_interface(a).ip))
            except ValueError as exc:
                raise ValueError(f"invalid IP address {a!r}") from exc
        return out

    @property
    def ip(self) -> Optional[str]:
        return self.ip_addresses[0] if self.ip_addresses else None

    @property
    def effective_default_action(self) -> Action:
        if self.default_action:
            return self.default_action
        return "DENY" if self.type == "firewall" else "ALLOW"


class Link(BaseModel):
    source: str
    destination: str
    cost: int = Field(1, gt=0)


class Route(BaseModel):
    """A static route held by ``router`` (any device may hold routes, e.g. a host default route)."""

    router: str
    destination: str
    next_hop: str
    metric: int = Field(10, ge=0)

    @field_validator("destination")
    @classmethod
    def _prefix(cls, v: str) -> str:
        return norm_prefix(v)


class AclRule(BaseModel):
    """One ordered ACL entry on ``node``. First match wins; endpoints may be a node id,
    an IP, a CIDR, or ``any``."""

    node: str
    source: str = "any"
    destination: str = "any"
    protocol: str = "ANY"
    port: Optional[int] = None
    action: Action

    @field_validator("protocol")
    @classmethod
    def _proto(cls, v: str) -> str:
        return norm_protocol(v)

    def describe(self) -> str:
        p = "" if self.port is None else f" port {self.port}"
        return f"{self.action} {self.source} -> {self.destination} {self.protocol}{p}"


class Flow(BaseModel):
    id: Optional[str] = None
    source: str
    destination: str
    protocol: str = "TCP"
    port: Optional[int] = None
    criticality: int = Field(1, ge=1, le=5)
    description: Optional[str] = None

    @field_validator("protocol")
    @classmethod
    def _proto(cls, v: str) -> str:
        return norm_protocol(v)

    @property
    def key(self) -> str:
        return traffic_key(self.source, self.destination, self.protocol, self.port)


class Policy(BaseModel):
    """A security requirement.

    ALLOW: the traffic must be delivered (and, if ``waypoint`` is set, cross that device).
    DENY:  the traffic must not be delivered.
    """

    id: Optional[str] = None
    source: str
    destination: str
    protocol: str = "TCP"
    port: Optional[int] = None
    action: Action
    waypoint: Optional[str] = None
    description: Optional[str] = None

    @field_validator("protocol")
    @classmethod
    def _proto(cls, v: str) -> str:
        return norm_protocol(v)

    @property
    def key(self) -> str:
        return traffic_key(self.source, self.destination, self.protocol, self.port)

    def describe(self) -> str:
        p = "" if self.port is None else f"/{self.port}"
        wp = f" via {self.waypoint}" if self.waypoint else ""
        return f"{self.action} {self.source} -> {self.destination} {self.protocol}{p}{wp}"


class Network(BaseModel):
    name: str = "network"
    nodes: list[Node]
    links: list[Link] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    acls: list[AclRule] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)
    policies: list[Policy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Network":
        errors: list[str] = []
        ids = [n.id for n in self.nodes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            errors.append(f"duplicate node ids: {sorted(dupes)}")
        known = set(ids)
        for l in self.links:
            for end in (l.source, l.destination):
                if end not in known:
                    errors.append(f"link {l.source}-{l.destination} references unknown node {end!r}")
            if l.source == l.destination:
                errors.append(f"link {l.source}-{l.destination} connects a node to itself")
        for r in self.routes:
            if r.router not in known:
                errors.append(f"route {r.destination} is held by unknown device {r.router!r}")
        for a in self.acls:
            if a.node not in known:
                errors.append(f"ACL rule refers to unknown device {a.node!r}")
        for f in self.flows:
            for end in (f.source, f.destination):
                if end not in known:
                    errors.append(f"flow {f.source}->{f.destination} references unknown node {end!r}")
        for p in self.policies:
            for end in (p.source, p.destination):
                if end not in known:
                    errors.append(f"policy {p.source}->{p.destination} references unknown node {end!r}")
            if p.waypoint and p.waypoint not in known:
                errors.append(f"policy waypoint {p.waypoint!r} is not a device in the network")
        if errors:
            raise ValueError("; ".join(errors))
        # assign stable ids to flows and policies that lack one
        used = {f.id for f in self.flows if f.id}
        n = 0
        for f in self.flows:
            if not f.id:
                n += 1
                while f"F{n}" in used:
                    n += 1
                f.id = f"F{n}"
                used.add(f.id)
        used = {p.id for p in self.policies if p.id}
        n = 0
        for p in self.policies:
            if not p.id:
                n += 1
                while f"P{n}" in used:
                    n += 1
                p.id = f"P{n}"
                used.add(p.id)
        return self


class Change(BaseModel):
    """One proposed configuration change.  Required fields depend on ``operation``:

    ADD_ROUTE       router, destination, next_hop, [metric]
    DELETE_ROUTE    router, destination, [next_hop]
    MODIFY_ROUTE    router, destination, new_next_hop, [old_next_hop], [new_metric]
    CHANGE_METRIC   router, destination, new_metric, [next_hop]
    ADD_LINK        node_a, node_b, [cost]
    DELETE_LINK     node_a, node_b
    ADD_ACL_RULE    rule, [position]
    DELETE_ACL_RULE rule  OR  node + rule_index
    ADD_POLICY      policy
    DELETE_POLICY   policy_id
    """

    operation: Operation
    router: Optional[str] = None
    destination: Optional[str] = None
    next_hop: Optional[str] = None
    metric: Optional[int] = None
    old_next_hop: Optional[str] = None
    new_next_hop: Optional[str] = None
    new_metric: Optional[int] = None
    node_a: Optional[str] = None
    node_b: Optional[str] = None
    cost: Optional[int] = None
    node: Optional[str] = None
    rule: Optional[AclRule] = None
    rule_index: Optional[int] = None
    position: Optional[int] = None
    policy: Optional[Policy] = None
    policy_id: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode="after")
    def _required(self) -> "Change":
        op = self.operation
        need: list[str] = []
        if op == "ADD_ROUTE":
            need = ["router", "destination", "next_hop"]
        elif op == "DELETE_ROUTE":
            need = ["router", "destination"]
        elif op == "MODIFY_ROUTE":
            need = ["router", "destination", "new_next_hop"]
        elif op == "CHANGE_METRIC":
            need = ["router", "destination", "new_metric"]
        elif op in ("ADD_LINK", "DELETE_LINK"):
            need = ["node_a", "node_b"]
        elif op == "ADD_ACL_RULE":
            need = ["rule"]
        elif op == "DELETE_ACL_RULE":
            if self.rule is None and not (self.node and self.rule_index is not None):
                raise ValueError("DELETE_ACL_RULE needs 'rule' or both 'node' and 'rule_index'")
        elif op == "ADD_POLICY":
            need = ["policy"]
        elif op == "DELETE_POLICY":
            need = ["policy_id"]
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{op} is missing required field(s): {', '.join(missing)}")
        if self.destination is not None and op in (
            "ADD_ROUTE", "DELETE_ROUTE", "MODIFY_ROUTE", "CHANGE_METRIC"
        ):
            self.destination = norm_prefix(self.destination)
        return self

    def describe(self) -> str:
        op = self.operation
        if op == "ADD_ROUTE":
            return f"Add route on {self.router}: {self.destination} via {self.next_hop}"
        if op == "DELETE_ROUTE":
            via = f" via {self.next_hop}" if self.next_hop else ""
            return f"Delete route on {self.router}: {self.destination}{via}"
        if op == "MODIFY_ROUTE":
            old = f"{self.old_next_hop} -> " if self.old_next_hop else "next hop -> "
            return f"Modify route on {self.router}: {self.destination} {old}{self.new_next_hop}"
        if op == "CHANGE_METRIC":
            return f"Change metric on {self.router}: {self.destination} to {self.new_metric}"
        if op == "ADD_LINK":
            return f"Add link {self.node_a} - {self.node_b}"
        if op == "DELETE_LINK":
            return f"Delete link {self.node_a} - {self.node_b}"
        if op == "ADD_ACL_RULE" and self.rule:
            return f"Add ACL rule on {self.rule.node}: {self.rule.describe()}"
        if op == "DELETE_ACL_RULE":
            if self.rule:
                return f"Delete ACL rule on {self.rule.node}: {self.rule.describe()}"
            return f"Delete ACL rule #{self.rule_index} on {self.node}"
        if op == "ADD_POLICY" and self.policy:
            return f"Add policy: {self.policy.describe()}"
        if op == "DELETE_POLICY":
            return f"Delete policy {self.policy_id}"
        return op
