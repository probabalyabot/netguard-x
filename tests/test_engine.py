import json

import pytest
from pydantic import ValidationError

from netguardx import Change, ChangeError, Network, analyze, apply_changes, verify_network
from netguardx.network import BLACKHOLE, DELIVERED, DROPPED_ACL, INVALID_NEXT_HOP, LOOP, NetworkState, simulate
from netguardx.nlp import interpret
from netguardx.risk import RiskWeights

from conftest import load_change


def canon(n):
    """Order-insensitive view of links/routes (a restored link is re-appended, order is not semantic)."""
    d = n.model_dump()
    d["links"] = sorted(json.dumps(x, sort_keys=True) for x in d["links"])
    d["routes"] = sorted(json.dumps(x, sort_keys=True) for x in d["routes"])
    return d


def types(report):
    return {f.type for f in report.findings}


# ------------------------------------------------------------------ baseline / forwarding
def test_baseline_satisfies_all_policies(net):
    rep = verify_network(net)
    assert rep.summary["policies_violated"] == 0
    assert rep.summary["static_issues"] == 0


def test_baseline_paths(net):
    st = NetworkState(net)
    t = simulate(st, "APP", "DB", "TCP", 5432)
    assert t.status == DELIVERED and t.path == ["APP", "R1", "R2", "FW", "DB"]
    t = simulate(st, "USER", "DB", "TCP", 5432)
    assert t.status == DROPPED_ACL and t.stop_node == "FW"
    t = simulate(st, "DB", "INET", "TCP", 443)
    assert t.status == DROPPED_ACL and t.hops[-1].acl.rule_index == 2


def test_longest_prefix_beats_lower_metric(net):
    net.routes.append(type(net.routes[0])(router="R1", destination="10.0.5.0/25", next_hop="R3", metric=99))
    st = NetworkState(net)
    t = simulate(st, "APP", "DB", "TCP", 5432)  # DB is 10.0.5.10, inside the /25
    assert t.path[:3] == ["APP", "R1", "R3"]


def test_lowest_metric_wins_at_equal_prefix(net):
    net.routes.append(type(net.routes[0])(router="R1", destination="10.0.5.0/24", next_hop="R3", metric=5))
    assert simulate(NetworkState(net), "APP", "DB", "TCP", 5432).path[2] == "R3"


def test_blackhole_when_no_route(net):
    net.routes = [r for r in net.routes if not (r.router == "R1" and r.destination == "0.0.0.0/0")]
    net.routes = [r for r in net.routes if not (r.router == "R1" and r.destination == "10.0.5.0/24")]
    t = simulate(NetworkState(net), "APP", "DB", "TCP", 5432)
    assert t.status == BLACKHOLE and t.stop_node == "R1"


def test_firewall_default_deny_and_port_specific(net):
    st = NetworkState(net)
    assert simulate(st, "APP", "DB", "TCP", 3306).status == DROPPED_ACL  # only 5432 is allowed
    assert simulate(st, "APP", "DB", "UDP", 5432).status == DROPPED_ACL


# ------------------------------------------------------------------------- changes
def test_apply_changes_never_mutates_input(net):
    before = net.model_dump()
    apply_changes(net, load_change("route-via-r3"))
    assert net.model_dump() == before


@pytest.mark.parametrize("name", ["route-via-r3", "route-loop", "remove-r1-r2", "open-firewall", "backup-link", "safe-metric"])
def test_inverse_restores_original(net, name):
    ch = load_change(name)
    cf, inverses, _ = apply_changes(net, ch)
    restored, _, _ = apply_changes(cf, list(reversed(inverses)))
    assert canon(restored) == canon(net)


def test_change_errors(net):
    with pytest.raises(ChangeError):
        apply_changes(net, [Change(operation="DELETE_ROUTE", router="R1", destination="192.0.2.0/24")])
    with pytest.raises(ChangeError):
        apply_changes(net, [Change(operation="DELETE_LINK", node_a="R2", node_b="R3")])
    with pytest.raises(ChangeError):
        apply_changes(net, [Change(operation="ADD_LINK", node_a="R1", node_b="NOPE")])
    with pytest.raises(ValidationError):
        Change(operation="MODIFY_ROUTE", router="R1", destination="10.0.5.0/24")  # no new next hop


def test_network_validation_reports_dangling_references():
    with pytest.raises(ValidationError) as e:
        Network.model_validate({"nodes": [{"id": "A"}], "links": [{"source": "A", "destination": "B"}]})
    assert "unknown node 'B'" in str(e.value)


# -------------------------------------------------------------------------- analysis
def test_route_via_r3_bypasses_firewall(net):
    r = analyze(net, load_change("route-via-r3"))
    assert r.verdict["decision"] == "NOT_RECOMMENDED"
    assert {"WAYPOINT_BYPASS", "POLICY_VIOLATION", "NEW_EXPOSURE"} <= types(r)
    bypass = next(f for f in r.findings if f.type == "WAYPOINT_BYPASS")
    assert bypass.before_path == ["APP", "R1", "R2", "FW", "DB"]
    assert bypass.after_path == ["APP", "R1", "R3", "DB"]
    assert bypass.root_change == 0
    kinds = [s.kind for s in bypass.propagation]
    assert kinds == ["change", "routing", "path", "enforcement", "policy", "impact"]
    assert r.summary["security_violations"] == 3
    assert r.risk.level == "CRITICAL"
    assert r.rollback["if_reverted"] == {"decision": "SAFE", "remaining_problems": 0}


def test_loop_is_detected_and_attributed(net):
    r = analyze(net, load_change("route-loop"))
    f = next(f for f in r.findings if f.type == "ROUTING_LOOP")
    assert (f.source, f.destination) == ("APP", "DB") and f.root_change == 0
    assert r.summary["routing_failures"] == 1
    # flows that were blocked before and now loop are not reported as breakage
    assert all(f.type != "FLOW_BLOCKED" for f in r.findings)


def test_deleted_link_leaves_invalid_next_hop(net):
    r = analyze(net, load_change("remove-r1-r2"))
    f = next(f for f in r.findings if f.type == "INVALID_NEXT_HOP")
    assert f.extra["after_detail"].startswith("R1 forwards")
    assert any("no link R1-R2" in w for w in r.config_warnings)
    assert r.summary["probes_newly_unreachable"] > 0


def test_open_firewall_is_a_security_violation_without_path_change_upstream(net):
    r = analyze(net, load_change("open-firewall"))
    assert r.summary["security_violations"] == 2
    f = next(f for f in r.findings if f.type == "POLICY_VIOLATION")
    assert f.propagation[1].label.startswith("FW now lets this traffic through")


def test_benign_path_change_is_review_not_failure(net):
    r = analyze(net, load_change("backup-link"))
    assert r.verdict["decision"] == "REVIEW"
    assert types(r) == {"PATH_CHANGED"}
    assert r.risk.score == 0


def test_irrelevant_change_is_safe(net):
    r = analyze(net, load_change("safe-metric"))
    assert r.verdict["decision"] == "SAFE" and not r.findings and r.summary["affected_flows"] == 0


def test_adding_a_policy_flags_existing_behaviour(net):
    ch = [Change(operation="ADD_POLICY", policy={"source": "APP", "destination": "INET", "protocol": "TCP",
                                                 "port": 443, "action": "DENY"})]
    r = analyze(net, ch)
    f = next(f for f in r.findings if f.type == "POLICY_VIOLATION")
    assert f.root_change == 0 and f.before_path == f.after_path


def test_multi_change_attribution_and_partial_rollback(net):
    ch = load_change("route-via-r3") + load_change("safe-metric")
    r = analyze(net, ch)
    assert {f.root_change for f in r.findings} == {0}
    assert [x["index"] for x in r.rollback["revert"]] == [0]  # the harmless metric change stays


def test_attribution_does_not_depend_on_change_order(net):
    # both are route changes on R1 whose prefixes cover DB; only the second is used by the traffic
    r = analyze(net, load_change("safe-metric") + load_change("route-via-r3"))
    assert {f.root_change for f in r.findings} == {1}
    assert [x["index"] for x in r.rollback["revert"]] == [1]
    assert r.rollback["if_reverted"] == {"decision": "SAFE", "remaining_problems": 0}


def test_risk_weights_are_configurable(net):
    from netguardx import AnalysisOptions

    r = analyze(net, load_change("route-loop"), AnalysisOptions(weights=RiskWeights(broken_flows=0, routing_failures=0, criticality=0)))
    assert r.risk.score == 0


def test_preexisting_violation_not_blamed_on_change(net):
    net.acls = [a for a in net.acls if a.node != "FW"]
    net.nodes = [n.model_copy(update={"default_action": "ALLOW"}) if n.id == "FW" else n for n in net.nodes]
    base = verify_network(net)
    assert base.summary["policies_violated"] > 0
    r = analyze(net, load_change("safe-metric"))
    assert r.verdict["decision"] == "SAFE"
    assert r.summary["preexisting_violations"]


# -------------------------------------------------------------------------------- NLP
def test_nlp_parses_route_change_and_requirements(net):
    r = interpret("Change the route on R1 for 10.0.5.0/24 to R3.", net)
    assert r["changes"] == [{"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24", "new_next_hop": "R3"}]
    r = interpret("APP can reach DB through FW on port 5432, but DB must never access the internet", net)
    assert [(p["action"], p["source"], p["destination"]) for p in r["policies"]] == [("ALLOW", "APP", "DB"), ("DENY", "DB", "INET")]
    assert r["policies"][0]["waypoint"] == "FW" and r["policies"][0]["port"] == 5432
    assert interpret("make it faster", net)["unparsed"]


def test_nlp_route_phrasings(net):
    from netguardx.nlp import interpret
    for text in ["Change the route on R1 for 10.0.5.0/24 to use R3",
                 "Send traffic for 10.0.5.0/24 on R1 via R3"]:
        r = interpret(text, net)
        assert r["unparsed"] == []
        assert r["changes"] == [{"operation": "MODIFY_ROUTE", "router": "R1",
                                 "destination": "10.0.5.0/24", "new_next_hop": "R3"}]
