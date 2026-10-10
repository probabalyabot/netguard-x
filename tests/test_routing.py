"""Unit tests for the forwarding simulation in network.py, on small hand-built networks."""
import pytest
from pydantic import ValidationError

from netguardx import Network
from netguardx.models import AclRule
from netguardx.network import (
    BLACKHOLE, DELIVERED, DROPPED_ACL, INVALID_NEXT_HOP, LOOP, NetworkState, simulate, static_issues,
)


def build(nodes, links, routes=(), acls=()):
    """nodes: {id: ip} or {id: (ip, type)} or {id: (ip, type, default_action)}."""
    out = []
    for nid, spec in nodes.items():
        spec = spec if isinstance(spec, tuple) else (spec,)
        n = {"id": nid, "ip_addresses": [spec[0]] if spec[0] else [], "type": spec[1] if len(spec) > 1 else "router"}
        if len(spec) > 2:
            n["default_action"] = spec[2]
        out.append(n)
    return Network.model_validate({
        "nodes": out,
        "links": [{"source": a, "destination": b} for a, b in links],
        "routes": [{"router": r, "destination": d, "next_hop": nh, **({"metric": m[0]} if m else {})}
                   for r, d, nh, *m in routes],
        "acls": [{"node": n, "action": act, **kw} for n, act, kw in acls],
    })


def run(net, src, dst, proto="TCP", port=80):
    return simulate(NetworkState(net), src, dst, proto, port)


def line(routes=None, acls=(), fw_type="router"):
    """H1 - R1 - R2 - H2"""
    nodes = {"H1": ("10.0.1.10", "host"), "R1": "10.255.0.1", "R2": ("10.255.0.2", fw_type),
             "H2": ("10.0.2.10", "server")}
    default = [("H1", "0.0.0.0/0", "R1"), ("R1", "10.0.2.0/24", "R2"),
               ("R2", "10.0.1.0/24", "R1"), ("H2", "0.0.0.0/0", "R2")]
    return build(nodes, [("H1", "R1"), ("R1", "R2"), ("R2", "H2")], default if routes is None else routes, acls)


def diamond(routes):
    """H1 - R1 - (R2 | R3) - H2"""
    nodes = {"H1": ("10.0.1.10", "host"), "R1": "10.255.0.1", "R2": "10.255.0.2", "R3": "10.255.0.3",
             "H2": ("10.0.2.10", "server")}
    links = [("H1", "R1"), ("R1", "R2"), ("R1", "R3"), ("R2", "H2"), ("R3", "H2")]
    return build(nodes, links, [("H1", "0.0.0.0/0", "R1")] + routes)


# ------------------------------------------------------------------- delivery and paths
def test_delivery_along_static_routes_in_both_directions():
    net = line()
    t = run(net, "H1", "H2")
    assert t.status == DELIVERED and t.delivered and t.path == ["H1", "R1", "R2", "H2"] and t.stop_node == "H2"
    assert run(net, "H2", "H1").path == ["H2", "R2", "R1", "H1"]


def test_trace_records_the_route_used_at_each_hop():
    t = run(line(), "H1", "H2")
    assert [h.node for h in t.hops] == t.path
    used = [(h.route.prefix, h.route.next_hop, h.route.origin) for h in t.hops[:-1]]
    assert used == [("0.0.0.0/0", "R1", "static"), ("10.0.2.0/24", "R2", "static"), ("10.0.2.10/32", "H2", "connected")]
    assert t.hops[-1].route is None  # the destination does not forward


def test_neighbours_are_reachable_without_any_route():
    net = build({"A": "10.0.0.1", "B": "10.0.0.2"}, [("A", "B")])
    assert run(net, "A", "B").path == ["A", "B"]
    assert run(net, "B", "A").path == ["B", "A"]  # links work in both directions


def test_traffic_to_self_is_delivered_at_once():
    t = run(line(), "H1", "H1")
    assert t.status == DELIVERED and t.path == ["H1"]


def test_same_input_gives_same_trace():
    net = line()
    assert run(net, "H1", "H2") == run(net, "H1", "H2")


# ------------------------------------------------------------------------ route selection
def test_longest_prefix_wins_over_a_better_metric():
    net = diamond([("R1", "10.0.2.0/24", "R2", 1), ("R1", "10.0.2.0/28", "R3", 200)])
    assert run(net, "H1", "H2").path == ["H1", "R1", "R3", "H2"]


def test_lowest_metric_wins_between_equal_prefixes():
    net = diamond([("R1", "10.0.2.0/24", "R2", 20), ("R1", "10.0.2.0/24", "R3", 5)])
    assert run(net, "H1", "H2").path[2] == "R3"


def test_equal_prefix_and_metric_falls_back_to_next_hop_name():
    net = diamond([("R1", "10.0.2.0/24", "R3", 5), ("R1", "10.0.2.0/24", "R2", 5)])
    assert run(net, "H1", "H2").path[2] == "R2"


def test_default_route_is_used_only_when_nothing_more_specific_matches():
    net = diamond([("R1", "0.0.0.0/0", "R2"), ("R1", "10.0.9.0/24", "R3")])
    assert run(net, "H1", "H2").path[2] == "R2"  # 10.0.2.10 is not in 10.0.9.0/24
    net = diamond([("R1", "0.0.0.0/0", "R2"), ("R1", "10.0.2.0/24", "R3")])
    assert run(net, "H1", "H2").path[2] == "R3"


def test_direct_attachment_beats_a_static_route_pointing_away():
    # R2 is cabled to H2; a /24 and even a host route with a normal metric must not pull traffic back
    for prefix in ("10.0.2.0/24", "10.0.2.10/32"):
        net = diamond([("R1", "10.0.2.0/24", "R2"), ("R2", prefix, "R1")])
        assert run(net, "H1", "H2").path == ["H1", "R1", "R2", "H2"]


def test_route_prefix_with_host_bits_is_normalised():
    net = line(routes=[("H1", "0.0.0.0/0", "R1"), ("R1", "10.0.2.77/24", "R2")])
    assert net.routes[1].destination == "10.0.2.0/24"
    assert run(net, "H1", "H2").delivered


def test_address_written_with_a_mask_is_accepted():
    net = build({"A": "10.0.0.1/24", "B": "10.0.0.2/24"}, [("A", "B")])
    assert net.nodes[0].ip_addresses == ["10.0.0.1"] and run(net, "A", "B").delivered


def test_bad_addresses_and_prefixes_are_rejected():
    with pytest.raises(ValidationError):
        build({"A": "10.0.0.999"}, [])
    with pytest.raises(ValidationError):
        build({"A": "10.0.0.1", "B": "10.0.0.2"}, [("A", "B")], [("A", "not-a-prefix", "B")])


# ------------------------------------------------------------------------------ failures
def test_blackhole_where_the_route_is_missing():
    net = line(routes=[("H1", "0.0.0.0/0", "R1")])  # R1 knows nothing about 10.0.2.0/24
    t = run(net, "H1", "H2")
    assert t.status == BLACKHOLE and t.stop_node == "R1" and t.path == ["H1", "R1"]
    assert "no route to 10.0.2.10" in t.detail


def test_blackhole_at_a_source_with_no_route():
    t = run(line(routes=[]), "H1", "H2")
    assert t.status == BLACKHOLE and t.path == ["H1"]


def test_destination_without_an_address_or_unknown_device():
    net = build({"A": "10.0.0.1", "B": None}, [("A", "B")])
    t = run(net, "A", "B")
    assert t.status == BLACKHOLE and "no IP address" in t.detail
    assert run(net, "A", "NOPE").status == BLACKHOLE
    assert run(net, "NOPE", "A").status == BLACKHOLE


def test_forwarding_loop_is_detected():
    nodes = {"H1": ("10.0.1.10", "host"), "R1": "10.255.0.1", "R2": "10.255.0.2", "R3": "10.255.0.3",
             "H2": ("10.0.2.10", "server")}
    links = [("H1", "R1"), ("R1", "R2"), ("R2", "R3"), ("R3", "H2")]
    net = build(nodes, links, [("H1", "0.0.0.0/0", "R1"), ("R1", "10.0.2.0/24", "R2"), ("R2", "10.0.2.0/24", "R1")])
    t = run(net, "H1", "H2")
    assert t.status == LOOP and t.path == ["H1", "R1", "R2", "R1"] and t.stop_node == "R1"


def test_three_device_loop_is_detected():
    nodes = {"H1": ("10.0.1.10", "host"), "R1": "10.255.0.1", "R2": "10.255.0.2", "R3": "10.255.0.3",
             "H2": ("10.0.2.10", "server")}
    links = [("H1", "R1"), ("R1", "R2"), ("R2", "R3"), ("R3", "R1")]
    routes = [("H1", "0.0.0.0/0", "R1"), ("R1", "0.0.0.0/0", "R2"), ("R2", "0.0.0.0/0", "R3"), ("R3", "0.0.0.0/0", "R1")]
    t = run(build(nodes, links, routes), "H1", "H2")
    assert t.status == LOOP and t.path == ["H1", "R1", "R2", "R3", "R1"]


def test_next_hop_that_is_not_cabled():
    net = diamond([("R1", "10.0.2.0/24", "H2")])  # H2 exists but R1 has no link to it
    t = run(net, "H1", "H2")
    assert t.status == INVALID_NEXT_HOP and t.stop_node == "R1" and "no link R1-H2" in t.detail
    assert t.path == ["H1", "R1"]  # the packet never leaves R1


def test_next_hop_that_does_not_exist():
    net = diamond([("R1", "10.0.2.0/24", "GHOST")])
    t = run(net, "H1", "H2")
    assert t.status == INVALID_NEXT_HOP and "not a device" in t.detail


def test_static_issues_lists_unusable_next_hops_only():
    net = diamond([("R1", "10.0.2.0/24", "R2"), ("R1", "10.0.7.0/24", "H2"), ("R1", "10.0.8.0/24", "GHOST")])
    found = {(i.kind, i.prefix, i.next_hop) for i in static_issues(NetworkState(net))}
    assert found == {("UNLINKED_NEXT_HOP", "10.0.7.0/24", "H2"), ("UNKNOWN_NEXT_HOP", "10.0.8.0/24", "GHOST")}


# ---------------------------------------------------------------------------------- IPv6
def v6(routes):
    nodes = {"H1": ("2001:db8:1::10", "host"), "R1": "2001:db8:ff::1", "H2": ("2001:db8:2::10", "server"),
             "R2": "2001:db8:ff::2"}
    return build(nodes, [("H1", "R1"), ("R1", "R2"), ("R2", "H2")], routes)


def test_ipv6_routing():
    t = run(v6([("H1", "::/0", "R1"), ("R1", "2001:db8:2::/48", "R2")]), "H1", "H2")
    assert t.status == DELIVERED and t.path == ["H1", "R1", "R2", "H2"]


def test_ipv4_route_never_matches_an_ipv6_destination():
    t = run(v6([("H1", "0.0.0.0/0", "R1")]), "H1", "H2")
    assert t.status == BLACKHOLE and t.stop_node == "H1"


# ---------------------------------------------------------------------------------- ACLs
def test_first_matching_rule_wins():
    allow_then_deny = [("R2", "ALLOW", {"source": "H1"}), ("R2", "DENY", {})]
    t = run(line(acls=allow_then_deny), "H1", "H2")
    assert t.delivered and t.hops[2].acl.rule_index == 0
    deny_then_allow = [("R2", "DENY", {}), ("R2", "ALLOW", {"source": "H1"})]
    t = run(line(acls=deny_then_allow), "H1", "H2")
    assert t.status == DROPPED_ACL and t.stop_node == "R2" and t.path == ["H1", "R1", "R2"]
    assert t.hops[-1].acl.rule_index == 0


def test_firewall_denies_by_default_and_router_allows_by_default():
    rule = [("R2", "ALLOW", {"source": "H2"})]  # does not match H1 -> H2
    t = run(line(acls=rule, fw_type="firewall"), "H1", "H2")
    assert t.status == DROPPED_ACL and t.hops[-1].acl.rule == "default DENY" and t.hops[-1].acl.rule_index is None
    t = run(line(acls=rule), "H1", "H2")
    assert t.delivered and t.hops[2].acl.rule == "default ALLOW"


def test_firewall_with_no_rules_drops_everything_and_router_with_none_is_silent():
    assert run(line(fw_type="firewall"), "H1", "H2").status == DROPPED_ACL
    t = run(line(), "H1", "H2")
    assert all(h.acl is None for h in t.hops)


def test_explicit_default_action_overrides_the_device_type():
    nodes = {"H1": ("10.0.1.10", "host"), "R1": ("10.255.0.1", "router", "DENY"),
             "FW": ("10.255.0.2", "firewall", "ALLOW"), "H2": ("10.0.2.10", "server")}
    routes = [("H1", "0.0.0.0/0", "R1"), ("R1", "10.0.2.0/24", "FW")]
    net = build(nodes, [("H1", "R1"), ("R1", "FW"), ("FW", "H2")], routes)
    assert run(net, "H1", "H2").stop_node == "R1"
    net.nodes[1].default_action = None
    assert run(net, "H1", "H2").delivered  # the ALLOW-by-default firewall lets it through


def test_rule_matches_on_protocol_and_port():
    acls = [("R2", "ALLOW", {"source": "H1", "protocol": "tcp", "port": 443})]
    net = line(acls=acls, fw_type="firewall")
    assert run(net, "H1", "H2", "TCP", 443).delivered
    assert run(net, "H1", "H2", "tcp", 443).delivered  # protocol case does not matter
    assert run(net, "H1", "H2", "TCP", 80).status == DROPPED_ACL
    assert run(net, "H1", "H2", "UDP", 443).status == DROPPED_ACL
    assert run(net, "H1", "H2", "TCP", None).status == DROPPED_ACL  # a port rule needs that port


def test_rule_without_protocol_or_port_matches_all_services():
    net = line(acls=[("R2", "ALLOW", {"source": "H1", "protocol": "*"})], fw_type="firewall")
    assert run(net, "H1", "H2", "UDP", 53).delivered and run(net, "H1", "H2", "ICMP", None).delivered


@pytest.mark.parametrize("spec,delivered", [
    ("H1", True), ("10.0.1.10", True), ("10.0.1.0/24", True), ("any", True), ("*", True),
    ("10.0.9.0/24", False), ("10.0.1.11", False), ("H2", False), ("garbage", False),
])
def test_rule_source_forms(spec, delivered):
    net = line(acls=[("R2", "ALLOW", {"source": spec})], fw_type="firewall")
    assert run(net, "H1", "H2").delivered is delivered


def test_rule_destination_is_matched_too():
    net = line(acls=[("R2", "ALLOW", {"destination": "10.0.2.0/24"})], fw_type="firewall")
    assert run(net, "H1", "H2").delivered
    net = line(acls=[("R2", "ALLOW", {"destination": "10.0.3.0/24"})], fw_type="firewall")
    assert run(net, "H1", "H2").status == DROPPED_ACL


def test_acl_is_checked_before_routing():
    # R2 has no usable route here, but it must report the drop, not a missing route
    nodes = {"H1": ("10.0.1.10", "host"), "R1": "10.255.0.1", "R2": ("10.255.0.2", "firewall"),
             "H2": ("10.0.2.10", "server")}
    net = build(nodes, [("H1", "R1"), ("R1", "R2")], [("H1", "0.0.0.0/0", "R1"), ("R1", "10.0.2.0/24", "R2")])
    assert run(net, "H1", "H2").status == DROPPED_ACL


def test_source_does_not_filter_its_own_traffic_but_destination_does():
    nodes = {"A": ("10.0.0.1", "host", "DENY"), "B": ("10.0.0.2", "host")}
    assert run(build(nodes, [("A", "B")]), "A", "B").delivered
    nodes = {"A": ("10.0.0.1", "host"), "B": ("10.0.0.2", "host", "DENY")}
    t = run(build(nodes, [("A", "B")]), "A", "B")
    assert t.status == DROPPED_ACL and t.stop_node == "B"


def test_acl_on_one_device_does_not_affect_paths_that_avoid_it():
    net = diamond([("R1", "10.0.2.0/24", "R3")])
    net.acls.append(AclRule(node="R2", action="DENY"))
    assert run(net, "H1", "H2").path == ["H1", "R1", "R3", "H2"]
