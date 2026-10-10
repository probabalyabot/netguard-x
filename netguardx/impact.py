"""Differential configuration impact analysis (the core of NetGuard-X).

Pipeline for ``analyze(network, changes)``:

1. Apply the changes to a copy of the network -> counterfactual network.
2. Simulate every traffic class (declared flows, policy traffic, exposure probes) in both states.
3. Diff the two states per traffic class: status, path, policy outcome.
4. For every behavioural difference, locate the first device where forwarding diverges and
   attribute it to the change that touched that device / link / ACL (root cause).
5. Build a propagation chain  change -> forwarding decision -> path -> enforcement point ->
   policy -> impact, and merge all chains into one Configuration Impact Graph.
6. Score risk, choose a verdict, and (optionally) recommend which changes to revert and
   verify that reverting them clears the problems.
"""
from __future__ import annotations

import ipaddress
import time
from typing import Any, Callable, Optional

import networkx as nx
from pydantic import BaseModel, Field

from .changes import Effect, apply_changes
from .explain import FAILURE_TYPES, ROUTING_TYPES, SECURITY_TYPES, SEVERITY_RANK, compose, fmt_path
from .models import Change, Network
from .network import (
    BLACKHOLE, DROPPED_ACL, INVALID_NEXT_HOP, LOOP, Hop, NetworkState, Trace, simulate, static_issues,
)
from .risk import Risk, RiskWeights, calculate_risk
from .verify import PolicyResult, TrafficClass, build_classes, evaluate_policy


# ------------------------------------------------------------------------------- output models
class Step(BaseModel):
    kind: str  # change | routing | path | enforcement | policy | impact
    label: str
    detail: str = ""
    key: str


class Finding(BaseModel):
    id: str = ""
    type: str
    severity: str  # critical | high | medium | info
    title: str
    source: str
    destination: str
    flow_key: Optional[str] = None
    policies: list[str] = Field(default_factory=list)
    expected: Optional[str] = None
    observed: Optional[str] = None
    before_path: list[str] = Field(default_factory=list)
    after_path: list[str] = Field(default_factory=list)
    before_status: str = ""
    after_status: str = ""
    root_change: Optional[int] = None
    propagation: list[Step] = Field(default_factory=list)
    technical: str = ""
    human: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class FlowDelta(BaseModel):
    key: str
    source: str
    destination: str
    protocol: str
    port: Optional[int]
    flow_ids: list[str]
    policy_ids: list[str]
    expected: Optional[str]
    before: Trace
    after: Trace
    outcome: str  # path_changed | newly_reachable | newly_unreachable | status_changed
    added_devices: list[str]
    removed_devices: list[str]
    finding: Optional[str] = None


class AnalysisOptions(BaseModel):
    probes: bool = True
    probe_limit: int = 2000
    weights: RiskWeights = Field(default_factory=RiskWeights)
    rollback: bool = True


class ChangeReport(BaseModel):
    network: str
    changes: list[dict[str, Any]]
    verdict: dict[str, Any]
    summary: dict[str, Any]
    risk: Risk
    findings: list[Finding]
    flow_deltas: list[FlowDelta]
    policies: list[dict[str, Any]]
    config_warnings: list[str]
    rollback: Optional[dict[str, Any]] = None
    impact_graph: dict[str, Any]
    topology: dict[str, Any]
    meta: dict[str, Any]


# ---------------------------------------------------------------------------------- divergence
class Divergence(BaseModel):
    node: str
    index: int
    before_next: Optional[str]
    after_next: Optional[str]
    before_hop: Optional[Hop]
    after_hop: Optional[Hop]


def _hop_at(t: Trace, i: int) -> Optional[Hop]:
    return t.hops[i] if i < len(t.hops) else None


def find_divergence(tb: Trace, ta: Trace) -> Optional[Divergence]:
    """First device where the two traces stop agreeing on what happens to the packet."""
    for i in range(min(len(tb.path), len(ta.path))):
        nb = tb.path[i + 1] if i + 1 < len(tb.path) else None
        na = ta.path[i + 1] if i + 1 < len(ta.path) else None
        if nb != na:
            return Divergence(node=tb.path[i], index=i, before_next=nb, after_next=na,
                              before_hop=_hop_at(tb, i), after_hop=_hop_at(ta, i))
    if tb.status != ta.status or tb.stop_node != ta.stop_node:
        i = len(ta.path) - 1
        return Divergence(node=ta.path[i], index=i, before_next=None, after_next=None,
                          before_hop=_hop_at(tb, i), after_hop=_hop_at(ta, i))
    return None


def _decision_text(div: Divergence, ta: Trace) -> tuple[str, str]:
    node = div.node
    hb, ha = div.before_hop, div.after_hop
    rb = hb.route if hb else None
    ra = ha.route if ha else None
    acl_b = hb.acl if hb else None
    acl_a = ha.acl if ha else None
    if acl_a and acl_a.action == "DENY" and not (acl_b and acl_b.action == "DENY"):
        return f"{node} now drops this traffic", f"ACL on {node} matches: {acl_a.rule}."
    if acl_b and acl_b.action == "DENY" and not (acl_a and acl_a.action == "DENY"):
        now = acl_a.rule if acl_a else "no ACL applies"
        return (f"{node} now lets this traffic through",
                f"ACL on {node} used to drop it ({acl_b.rule}); now: {now}.")
    if rb and ra and (rb.prefix != ra.prefix or rb.next_hop != ra.next_hop):
        return (f"{node} selects a different route",
                f"{node} used {rb.prefix} via {rb.next_hop}; it now uses {ra.prefix} via {ra.next_hop}.")
    if ta.status == INVALID_NEXT_HOP and ta.stop_node == node:
        return f"{node} can no longer use its next hop", ta.detail + "."
    if ta.status == BLACKHOLE and ta.stop_node == node:
        return f"{node} has no matching route", ta.detail + "."
    return f"Forwarding at {node} differs", f"Next hop was {div.before_next}, now {div.after_next}."


def _attribute(effects: list[Effect], div: Optional[Divergence], dst_ip: Optional[str]) -> Optional[int]:
    """Which change explains the divergence?  Match on device, then link/prefix specifics."""
    if div is None:
        return None
    nexts = {div.before_next, div.after_next} - {None}
    ip = ipaddress.ip_address(dst_ip) if dst_ip else None
    scored: list[tuple[int, int]] = []
    for e in effects:
        score = 0
        if e.kind == "route" and div.node in e.nodes:
            covers = True
            if ip is not None and e.prefix:
                covers = ip in ipaddress.ip_network(e.prefix)
            score = 3 if covers else 1
        elif e.kind == "link" and div.node in e.nodes:
            score = 3 if (nexts & set(e.nodes)) else 1
        elif e.kind == "acl" and div.node in e.nodes:
            score = 3
        if score:
            scored.append((-score, e.index))
    if scored:
        return sorted(scored)[0][1]
    return None


# ---------------------------------------------------------------------------------- utilities
def _path_devices(before: Trace, after: Trace) -> tuple[list[str], list[str]]:
    added = [n for n in dict.fromkeys(after.path) if n not in before.path]
    removed = [n for n in dict.fromkeys(before.path) if n not in after.path]
    return added, removed


def _enforcement_points(state: NetworkState, waypoints: set[str]) -> set[str]:
    pts = set(waypoints)
    for nid, n in state.nodes.items():
        if n.type == "firewall" or state.acls.get(nid):
            pts.add(nid)
    return pts


def _build_chain(
    fid: str, ftype: str, root: Optional[int], changes: list[Change], div: Optional[Divergence],
    tb: Trace, ta: Trace, removed: list[str], enforcement: set[str], policy_notes: list[tuple[str, str]],
    impact: str, flow_key: str,
) -> list[Step]:
    steps: list[Step] = []
    if root is not None:
        steps.append(Step(kind="change", label=changes[root].describe(), key=f"change:{root}"))
    if div is not None:
        label, detail = _decision_text(div, ta)
        steps.append(Step(kind="routing", label=label, detail=detail,
                          key=f"decision:{div.node}:{root}:{div.before_next}:{div.after_next}"))
    if tb.path != ta.path:
        steps.append(Step(kind="path", label="Forwarding path changes",
                          detail=f"before: {fmt_path(tb.path)}\nafter: {fmt_path(ta.path)}", key=f"path:{flow_key}"))
    for dev in removed:
        if dev in enforcement:
            steps.append(Step(kind="enforcement", label=f"{dev} is no longer on the path",
                              detail=f"Traffic used to be handled by {dev}; it no longer is.", key=f"device:{dev}"))
    for pid, note in policy_notes:
        steps.append(Step(kind="policy", label=f"Policy {pid} is violated", detail=note, key=f"policy:{pid}"))
    steps.append(Step(kind="impact", label=impact, key=f"finding:{fid}"))
    return steps


def layout_topology(topology: dict[str, Any]) -> dict[str, Any]:
    """Give map coordinates to nodes that have none.  Presentation only: ``analyze`` does not call
    this, so verification never pays for a layout.  Whoever draws the map does."""
    nodes = {n["id"]: n for n in topology["nodes"]}
    if any(v["x"] is None or v["y"] is None for v in nodes.values()):
        g = nx.Graph()
        g.add_nodes_from(nodes)
        g.add_edges_from((l["source"], l["destination"]) for l in topology["links"])
        fixed = {k: (v["x"], v["y"]) for k, v in nodes.items() if v["x"] is not None and v["y"] is not None}
        pos = nx.spring_layout(g, seed=7, pos=fixed or None, fixed=list(fixed) or None)
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        span_x = (max(xs) - min(xs)) or 1
        span_y = (max(ys) - min(ys)) or 1
        for k, v in nodes.items():
            if v["x"] is None or v["y"] is None:
                v["x"] = round(float((pos[k][0] - min(xs)) / span_x), 4)
                v["y"] = round(float((pos[k][1] - min(ys)) / span_y), 4)
    return topology


def _topology(before: Network, after: Network) -> dict[str, Any]:
    nodes: dict[str, dict] = {}
    for net in (before, after):
        for n in net.nodes:
            nodes.setdefault(n.id, {"id": n.id, "type": n.type, "label": n.label or n.id, "ip": n.ip,
                                    "x": n.x, "y": n.y, "criticality": n.criticality})
    lb = {frozenset((l.source, l.destination)): l for l in before.links}
    la = {frozenset((l.source, l.destination)): l for l in after.links}
    links = []
    for k in list(lb) + [k for k in la if k not in lb]:
        l = lb.get(k) or la.get(k)
        status = "unchanged" if (k in lb and k in la) else ("removed" if k in lb else "added")
        links.append({"source": l.source, "destination": l.destination, "status": status})
    return {"nodes": list(nodes.values()), "links": links}


def _impact_graph(findings: list[Finding]) -> dict[str, Any]:
    """Merge every finding's propagation chain into one Configuration Impact Graph (CIG)."""
    g = nx.DiGraph()
    for f in findings:
        prev = None
        for s in f.propagation:
            if s.key not in g:
                g.add_node(s.key, kind=s.kind, label=s.label)
            if prev is not None:
                g.add_edge(prev, s.key)
            prev = s.key
    return {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v} for u, v in g.edges()],
    }


# --------------------------------------------------------------------------------- the engine
_FAIL_MAP = {LOOP: "ROUTING_LOOP", BLACKHOLE: "BLACKHOLE", INVALID_NEXT_HOP: "INVALID_NEXT_HOP", DROPPED_ACL: "FLOW_BLOCKED"}


def analyze(network: Network, changes: list[Change], options: Optional[AnalysisOptions] = None) -> ChangeReport:
    opts = options or AnalysisOptions()
    t0 = time.perf_counter()

    cf_net, inverses, effects = apply_changes(network, changes)
    before, after = NetworkState(network), NetworkState(cf_net)

    classes = build_classes([network, cf_net], probes=opts.probes, probe_limit=opts.probe_limit)
    tb = {k: simulate(before, c.source, c.destination, c.protocol, c.port) for k, c in classes.items()}
    ta = {k: simulate(after, c.source, c.destination, c.protocol, c.port) for k, c in classes.items()}
    return assess(network, cf_net, changes, inverses, effects, before, after, classes, tb, ta, opts, t0, analyze)


def assess(
    network: Network, cf_net: Network, changes: list[Change], inverses: list[Change], effects: list[Effect],
    before: NetworkState, after: NetworkState, classes: dict[str, TrafficClass],
    tb: dict[str, Trace], ta: dict[str, Trace], opts: AnalysisOptions, t0: float,
    reanalyze: Callable[[Network, list[Change], AnalysisOptions], "ChangeReport"],
) -> ChangeReport:
    """Steps 3-6 of the pipeline, given both states and a trace of every class in each.

    How the traces were obtained is the caller's business: ``analyze`` simulates everything, the
    incremental verifier reuses cached traces.  ``reanalyze`` checks the rollback recommendation.
    """
    pol_b ={p.id: evaluate_policy(p, tb[p.key]) for p in network.policies}
    pol_a = {p.id: evaluate_policy(p, ta[p.key]) for p in cf_net.policies}
    pols_at: dict[str, list] = {}
    for p in cf_net.policies:
        pols_at.setdefault(p.key, []).append(p)
    policy_by_id = {p.id: p for p in cf_net.policies}
    policy_by_id.update({p.id: p for p in network.policies if p.id not in policy_by_id})

    enforcement_after_wp = {p.waypoint for p in cf_net.policies if p.waypoint} | {p.waypoint for p in network.policies if p.waypoint}
    enforcement = _enforcement_points(before, enforcement_after_wp)

    findings: list[Finding] = []
    deltas: list[FlowDelta] = []
    exposure: dict[str, dict[str, Any]] = {}
    exposure_pairs: set[tuple[str, str]] = set()
    probes_new = probes_lost = 0
    broken = routing_fail = violations = crit_excess = 0
    resolved: list[str] = []

    for key, c in classes.items():
        b, a = tb[key], ta[key]
        changed = b.path != a.path or b.status != a.status

        if not c.declared:
            if changed and not b.delivered and a.delivered:
                probes_new += 1
                exposure_pairs.add((c.source, c.destination))
                g = exposure.setdefault(c.destination, {"sources": set(), "services": set(), "example": key})
                g["sources"].add(c.source)
                g["services"].add(f"{c.protocol}" if c.port is None else f"{c.protocol}/{c.port}")
            elif changed and b.delivered and not a.delivered:
                probes_lost += 1
            continue

        pols = pols_at.get(key, [])
        viol_after = [pol_a[p.id] for p in pols if not pol_a[p.id].satisfied]
        new_viol = [v for v in viol_after if v.policy_id not in pol_b or pol_b[v.policy_id].satisfied]
        just_resolved = [p.id for p in pols if p.id in pol_b and not pol_b[p.id].satisfied and pol_a[p.id].satisfied]
        resolved.extend(just_resolved)
        wants_block_only = bool(pols) and all(p.action == "DENY" for p in pols)
        expected = None
        if pols:
            acts = {p.action for p in pols}
            expected = acts.pop() if len(acts) == 1 else "MIXED"

        ftype: Optional[str] = None
        if b.delivered and not a.delivered and not wants_block_only:
            ftype = _FAIL_MAP[a.status]
        elif new_viol:
            kinds = {v.violation for v in new_viol}
            if "denied_traffic_delivered" in kinds:
                ftype = "POLICY_VIOLATION"
            elif "waypoint_bypassed" in kinds:
                ftype = "WAYPOINT_BYPASS"
            else:
                ftype = _FAIL_MAP.get(a.status, "FLOW_BLOCKED")
        elif changed:
            if not b.delivered and a.delivered:
                ftype = "FLOW_RESTORED" if just_resolved else "NEW_REACHABILITY"
            elif b.delivered and a.delivered and b.path != a.path:
                ftype = "PATH_CHANGED"

        added, removed = _path_devices(b, a)
        if changed:
            if b.delivered and not a.delivered:
                outcome = "newly_unreachable"
            elif not b.delivered and a.delivered:
                outcome = "newly_reachable"
            elif b.status != a.status:
                outcome = "status_changed"
            else:
                outcome = "path_changed"
            deltas.append(FlowDelta(
                key=key, source=c.source, destination=c.destination, protocol=c.protocol, port=c.port,
                flow_ids=c.flow_ids, policy_ids=[p.id for p in pols], expected=expected, before=b, after=a,
                outcome=outcome, added_devices=added, removed_devices=removed,
            ))
        if ftype is None:
            continue

        div = find_divergence(b, a) if changed else None
        dst_ip = after.primary_ip(c.destination)
        root = _attribute(effects, div, dst_ip)
        if root is None and new_viol:
            new_ids = {v.policy_id for v in new_viol}
            for e in effects:
                if e.kind == "policy" and e.policy_id in new_ids:
                    root = e.index
                    break
        if root is None and len(effects) == 1:
            root = 0

        policy_notes = [(v.policy_id, f"{policy_by_id[v.policy_id].describe()}: {v.reason}") for v in new_viol
                        if v.violation in ("denied_traffic_delivered", "waypoint_bypassed")]
        waypoint = next((policy_by_id[v.policy_id].waypoint for v in new_viol if v.violation == "waypoint_bypassed"), None)
        decision = None
        if div is not None:
            lab, det = _decision_text(div, a)
            decision = f"{lab}: {det}"
        ctx = {
            "src": c.source, "dst": c.destination, "proto": c.protocol, "port": c.port,
            "before_path": b.path, "after_path": a.path, "before_detail": b.detail, "after_detail": a.detail,
            "stop_node": a.stop_node, "root": changes[root].describe() if root is not None else None,
            "decision": decision, "policies": [v.policy_id for v in new_viol], "waypoint": waypoint,
        }
        title, technical, human, impact = compose(ftype, ctx)

        if ftype in FAILURE_TYPES:
            broken += 1
            crit_excess += c.criticality - 1
        if ftype in ROUTING_TYPES:
            routing_fail += 1
        if ftype in SECURITY_TYPES:
            crit_excess += c.criticality - 1
        violations += sum(1 for v in new_viol if v.violation in ("denied_traffic_delivered", "waypoint_bypassed"))
        if ftype == "POLICY_VIOLATION":
            exposure_pairs.add((c.source, c.destination))

        severity = {"POLICY_VIOLATION": "critical", "WAYPOINT_BYPASS": "high"}.get(ftype)
        if severity is None:
            if ftype in FAILURE_TYPES:
                severity = "critical" if c.criticality >= 4 else "high"
            else:
                severity = "info"
        observed = "DELIVERED" if a.delivered else a.status
        f = Finding(
            type=ftype, severity=severity, title=title, source=c.source, destination=c.destination, flow_key=key,
            policies=[p.id for p in pols], expected=expected, observed=observed,
            before_path=b.path, after_path=a.path, before_status=b.status, after_status=a.status,
            root_change=root, technical=technical, human=human,
            extra={"violations": [v.model_dump() for v in new_viol], "criticality": c.criticality,
                   "before_detail": b.detail, "after_detail": a.detail},
        )
        f.propagation = _build_chain("{fid}", ftype, root, changes, div, b, a, removed, enforcement,
                                     policy_notes, impact, key)
        findings.append(f)

    # exposure findings (one per newly reachable destination)
    for dst, g in sorted(exposure.items()):
        ex_key = g["example"]
        b, a = tb[ex_key], ta[ex_key]
        div = find_divergence(b, a)
        root = _attribute(effects, div, after.primary_ip(dst))
        if root is None and len(effects) == 1:
            root = 0
        sources = sorted(g["sources"])
        services = sorted(g["services"])
        added, removed = _path_devices(b, a)
        decision = None
        if div is not None:
            lab, det = _decision_text(div, a)
            decision = f"{lab}: {det}"
        ctx = {
            "src": sources[0], "dst": dst, "proto": classes[ex_key].protocol, "port": classes[ex_key].port,
            "before_path": b.path, "after_path": a.path, "before_detail": b.detail, "after_detail": a.detail,
            "stop_node": a.stop_node, "root": changes[root].describe() if root is not None else None,
            "decision": decision, "policies": [], "sources": sources, "services": services,
        }
        title, technical, human, impact = compose("NEW_EXPOSURE", ctx)
        internet = any(after.nodes[s].type == "internet" for s in sources)
        crit = max(classes[ex_key].criticality, after.nodes[dst].criticality)
        crit_excess += crit - 1
        f = Finding(
            type="NEW_EXPOSURE", severity="high" if internet else "medium", title=title,
            source=", ".join(sources), destination=dst, flow_key=ex_key, expected=None, observed="DELIVERED",
            before_path=b.path, after_path=a.path, before_status=b.status, after_status=a.status,
            root_change=root, technical=technical, human=human,
            extra={"sources": sources, "services": services, "criticality": crit, "from_internet": internet},
        )
        f.propagation = _build_chain("{fid}", "NEW_EXPOSURE", root, changes, div, b, a, removed, enforcement, [],
                                     impact, ex_key)
        findings.append(f)

    # order findings and give them stable ids; patch the placeholder in the final chain step
    findings.sort(key=lambda f: (SEVERITY_RANK[f.severity], f.destination, f.source))
    for i, f in enumerate(findings, 1):
        f.id = f"FND-{i:02d}"
        for s in f.propagation:
            if "{fid}" in s.key:
                s.key = s.key.replace("{fid}", f.id)
        for d in deltas:
            if d.key == f.flow_key:
                d.finding = f.id

    # policies view
    pol_view = []
    for pid in list(dict.fromkeys(list(pol_b) + list(pol_a))):
        pb, pa = pol_b.get(pid), pol_a.get(pid)
        if pb is None:
            status = "added" if (pa and pa.satisfied) else "new_violation"
        elif pa is None:
            status = "removed"
        elif pb.satisfied and pa.satisfied:
            status = "ok"
        elif pb.satisfied and not pa.satisfied:
            status = "new_violation"
        elif not pb.satisfied and pa.satisfied:
            status = "resolved"
        else:
            status = "preexisting_violation"
        pol_view.append({
            "id": pid, "description": policy_by_id[pid].describe(), "status": status,
            "before": pb.model_dump() if pb else None, "after": pa.model_dump() if pa else None,
        })

    sb = {i.key(): i for i in static_issues(before)}
    sa = {i.key(): i for i in static_issues(after)}
    warnings = [i.message for k, i in sa.items() if k not in sb]

    negatives = [f for f in findings if f.severity in ("critical", "high")]
    review = [f for f in findings if f.severity in ("medium",)]
    declared_total = sum(1 for c in classes.values() if c.declared)
    affected = len(deltas)
    summary = {
        "declared_flows_checked": declared_total,
        "affected_flows": affected,
        "unchanged_flows": declared_total - affected,
        "broken_flows": broken,
        "routing_failures": routing_fail,
        "security_violations": violations,
        "new_exposures": len(exposure_pairs),
        "path_changes": sum(1 for f in findings if f.type == "PATH_CHANGED"),
        "probes_checked": sum(1 for c in classes.values() if not c.declared),
        "probes_newly_reachable": probes_new,
        "probes_newly_unreachable": probes_lost,
        "resolved_policies": sorted(set(resolved)),
        "preexisting_violations": [p["id"] for p in pol_view if p["status"] == "preexisting_violation"],
    }
    risk = calculate_risk(broken, violations, len(exposure_pairs), routing_fail, crit_excess, opts.weights)

    # verdict
    if negatives:
        top = negatives[0]
        extra = len(negatives) - 1
        headline = f"Do not deploy as is: {top.title}"
        if extra:
            headline += f" (and {extra} more problem{'s' if extra > 1 else ''})"
        decision = "NOT_RECOMMENDED"
    elif review:
        decision = "REVIEW"
        headline = f"Review before deploying: {review[0].title}"
    elif findings:
        decision = "REVIEW"
        n = len(findings)
        if all(f.type == "PATH_CHANGED" for f in findings):
            headline = (f"{n} flow takes a different path; no policy is broken" if n == 1
                        else f"{n} flows take a different path; no policy is broken")
        else:
            headline = (f"{n} flow behaves differently; no policy is broken" if n == 1
                        else f"{n} flows behave differently; no policy is broken")
    elif changes and deltas:
        decision = "SAFE"
        headline = "No policy is broken and no required flow is lost"
    else:
        decision = "SAFE"
        headline = "No declared flow or policy behaves differently after this change"
    verdict = {"decision": decision, "headline": headline}

    report = ChangeReport(
        network=network.name,
        changes=[{"index": i, "operation": c.operation, "description": c.describe(),
                  "inverse": inverses[i].model_dump(exclude_none=True), "effect": effects[i].model_dump(exclude_none=True)}
                 for i, c in enumerate(changes)],
        verdict=verdict, summary=summary, risk=risk, findings=findings, flow_deltas=deltas, policies=pol_view,
        config_warnings=warnings, rollback=None, impact_graph=_impact_graph(findings),
        topology=_topology(network, cf_net),
        meta={"classes": len(classes), "declared": declared_total, "probes_enabled": opts.probes,
              "duration_ms": round((time.perf_counter() - t0) * 1000, 1)},
    )

    if opts.rollback and negatives:
        culprits = sorted({f.root_change for f in negatives if f.root_change is not None}) or list(range(len(changes)))
        remaining = [c for i, c in enumerate(changes) if i not in culprits]
        residual = reanalyze(network, remaining, opts.model_copy(update={"rollback": False}))
        residual_bad = [f for f in residual.findings if f.severity in ("critical", "high")]
        report.rollback = {
            "revert": [{"index": i, "description": changes[i].describe(),
                        "revert_with": inverses[i].model_dump(exclude_none=True)} for i in culprits],
            "if_reverted": {"decision": residual.verdict["decision"], "remaining_problems": len(residual_bad)},
            "note": "Recommendation only. NetGuard-X never deploys or reverts configuration.",
        }
    return report
