"""Baseline verification: simulate declared flows, policies and exposure probes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from .models import ENDPOINT_TYPES, Network, Policy, norm_protocol, traffic_key
from .network import NetworkState, Trace, simulate, static_issues


@dataclass
class TrafficClass:
    key: str
    source: str
    destination: str
    protocol: str
    port: Optional[int]
    declared: bool  # comes from a flow or policy (as opposed to an exposure probe)
    flow_ids: list[str] = field(default_factory=list)
    criticality: int = 1


class PolicyResult(BaseModel):
    policy_id: str
    action: str
    satisfied: bool
    violation: Optional[str] = None  # not_delivered | waypoint_bypassed | denied_traffic_delivered
    reason: str = ""


def evaluate_policy(p: Policy, trace: Trace) -> PolicyResult:
    if p.action == "ALLOW":
        if not trace.delivered:
            return PolicyResult(policy_id=p.id, action=p.action, satisfied=False, violation="not_delivered",
                                reason=f"required traffic is not delivered: {trace.detail}")
        if p.waypoint and p.waypoint not in trace.path:
            return PolicyResult(policy_id=p.id, action=p.action, satisfied=False, violation="waypoint_bypassed",
                                reason=f"traffic is delivered but does not pass through {p.waypoint}: "
                                       + " -> ".join(trace.path))
        return PolicyResult(policy_id=p.id, action=p.action, satisfied=True, reason="required traffic is delivered")
    if trace.delivered:
        return PolicyResult(policy_id=p.id, action=p.action, satisfied=False, violation="denied_traffic_delivered",
                            reason="forbidden traffic is delivered: " + " -> ".join(trace.path))
    return PolicyResult(policy_id=p.id, action=p.action, satisfied=True, reason=f"forbidden traffic is blocked: {trace.detail}")


def build_classes(nets: list[Network], probes: bool = True, probe_limit: int = 2000) -> dict[str, TrafficClass]:
    """Union of declared flows/policies across the given networks, plus optional exposure probes.

    Probes try every ordered pair of endpoint devices on each service (protocol/port) that appears
    anywhere in the configuration, so the analysis can spot reachability nobody declared.
    """
    classes: dict[str, TrafficClass] = {}
    node_crit: dict[str, int] = {}
    for net in nets:
        for n in net.nodes:
            node_crit[n.id] = max(node_crit.get(n.id, 1), n.criticality)

    def add(key, s, d, proto, port, flow_id=None, crit=1):
        tc = classes.get(key)
        if tc is None:
            tc = TrafficClass(key, s, d, proto, port, True)
            classes[key] = tc
        tc.declared = True
        if flow_id and flow_id not in tc.flow_ids:
            tc.flow_ids.append(flow_id)
        tc.criticality = max(tc.criticality, crit)

    for net in nets:
        for f in net.flows:
            add(f.key, f.source, f.destination, f.protocol, f.port, f.id, f.criticality)
        for p in net.policies:
            add(p.key, p.source, p.destination, p.protocol, p.port)
    for tc in classes.values():
        tc.criticality = max(tc.criticality, node_crit.get(tc.source, 1), node_crit.get(tc.destination, 1))

    if probes:
        services: set[tuple[str, Optional[int]]] = set()
        for net in nets:
            for f in net.flows:
                services.add((f.protocol, f.port))
            for p in net.policies:
                services.add((p.protocol, p.port))
            for a in net.acls:
                if a.port is not None:
                    services.add((a.protocol if a.protocol != "ANY" else "TCP", a.port))
        endpoints = sorted({n.id for net in nets for n in net.nodes if n.type in ENDPOINT_TYPES})
        count = 0
        for s in endpoints:
            for d in endpoints:
                if s == d:
                    continue
                for proto, port in sorted(services, key=lambda x: (x[0], x[1] or 0)):
                    key = traffic_key(s, d, proto, port)
                    if key in classes:
                        continue
                    if count >= probe_limit:
                        return classes
                    classes[key] = TrafficClass(key, s, d, norm_protocol(proto), port, False,
                                                criticality=max(node_crit.get(s, 1), node_crit.get(d, 1)))
                    count += 1
    return classes


class BaselineReport(BaseModel):
    network: str
    traces: list[Trace]
    policy_results: list[PolicyResult]
    static_issues: list[dict]
    summary: dict


def verify_network(net: Network) -> BaselineReport:
    """Check the network as it is today (no change applied)."""
    state = NetworkState(net)
    classes = build_classes([net], probes=False)
    traces = {k: simulate(state, c.source, c.destination, c.protocol, c.port) for k, c in classes.items()}
    results = [evaluate_policy(p, traces[p.key]) for p in net.policies]
    issues = [vars(i) for i in static_issues(state)]
    failing = [t for t in traces.values() if not t.delivered]
    summary = {
        "flows_checked": len(traces),
        "delivered": len(traces) - len(failing),
        "not_delivered": len(failing),
        "policies": len(results),
        "policies_satisfied": sum(r.satisfied for r in results),
        "policies_violated": sum(not r.satisfied for r in results),
        "static_issues": len(issues),
    }
    return BaselineReport(network=net.name, traces=list(traces.values()), policy_results=results,
                          static_issues=issues, summary=summary)
