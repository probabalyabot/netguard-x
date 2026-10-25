"""Route changes in plain English and Cisco style (netguardx/nlp/routes.py), on the three-tier network."""
import pytest

from netguardx import Change, apply_changes
from netguardx.eval.topologies import campus_network
from netguardx.nlp import interpret


def changes(text, net):
    r = interpret(text, net)
    assert not r["unparsed"], r["unparsed"]
    return r["changes"]


def reason(text, net):
    r = interpret(text, net)
    assert not r["changes"] and len(r["unparsed"]) == 1, r
    return r["unparsed"][0]["reason"]


# ------------------------------------------------------------------------------------- plain English
@pytest.mark.parametrize("text,expected", [
    ("change the route on R1 for 10.0.5.0/24 to R3",
     {"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24", "new_next_hop": "R3"}),
    ("send DB traffic on R1 via R3",  # a device as the destination: R1's route covering DB
     {"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24", "new_next_hop": "R3"}),
    ("change R1's route for DB from R2 to R3",
     {"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24", "old_next_hop": "R2", "new_next_hop": "R3"}),
    ("point R2 at R1 for 10.0.5.0/24",
     {"operation": "MODIFY_ROUTE", "router": "R2", "destination": "10.0.5.0/24", "new_next_hop": "R1"}),
    ("route 10.0.5.0/24 on R1 via 10.255.0.3",  # next hop given as an address
     {"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.0.5.0/24", "new_next_hop": "R3"}),
    ("add a route on R1 to 10.0.7.0/24 via R3 with metric 20",
     {"operation": "ADD_ROUTE", "router": "R1", "destination": "10.0.7.0/24", "next_hop": "R3", "metric": 20}),
    ("add a route on R1 for 10.0.7.0 255.255.255.0 via R3",
     {"operation": "ADD_ROUTE", "router": "R1", "destination": "10.0.7.0/24", "next_hop": "R3"}),
    ("add a route on R3 to USER via R1",  # no specific route on R3 for USER: a host route
     {"operation": "ADD_ROUTE", "router": "R3", "destination": "10.0.0.10/32", "next_hop": "R1"}),
    ("remove the default route on R1",
     {"operation": "DELETE_ROUTE", "router": "R1", "destination": "0.0.0.0/0"}),
    ("delete the route on R2 to DB",
     {"operation": "DELETE_ROUTE", "router": "R2", "destination": "10.0.5.0/24"}),
    ("set the metric of R1's default route to 50",
     {"operation": "CHANGE_METRIC", "router": "R1", "destination": "0.0.0.0/0", "new_metric": 50}),
    ("change the metric of the route on R2 for 10.0.5.0/24 to 7",
     {"operation": "CHANGE_METRIC", "router": "R2", "destination": "10.0.5.0/24", "new_metric": 7}),
])
def test_plain_english(net, text, expected):
    assert changes(text, net) == [expected]


# ------------------------------------------------------------------------------------- Cisco style
@pytest.mark.parametrize("text,expected", [
    ("R1(config)# ip route 10.0.7.0 255.255.255.0 R3",
     {"operation": "ADD_ROUTE", "router": "R1", "destination": "10.0.7.0/24", "next_hop": "R3"}),
    ("R1# ip route 10.0.7.0 255.255.255.0 10.255.0.3 20",
     {"operation": "ADD_ROUTE", "router": "R1", "destination": "10.0.7.0/24", "next_hop": "R3", "metric": 20}),
    ("on R1: no ip route 0.0.0.0 0.0.0.0 INET",
     {"operation": "DELETE_ROUTE", "router": "R1", "destination": "0.0.0.0/0", "next_hop": "INET"}),
    ("ip route 10.0.7.0/24 R3 on R1",
     {"operation": "ADD_ROUTE", "router": "R1", "destination": "10.0.7.0/24", "next_hop": "R3"}),
])
def test_cisco_lines(net, text, expected):
    assert changes(text, net) == [expected]


def test_a_header_applies_to_the_lines_below_it(net):
    block = """conf t
R1(config)#
ip route 10.0.7.0 255.255.255.0 R3
no ip route 10.0.6.0 255.255.255.0 R2
!
R2(config)#
ip route 10.0.7.0 255.255.255.0 R1
end"""
    assert [(c["operation"], c["router"]) for c in changes(block, net)] == [
        ("ADD_ROUTE", "R1"), ("DELETE_ROUTE", "R1"), ("ADD_ROUTE", "R2")]


def test_a_line_naming_its_own_router_overrides_the_header(net):
    assert changes("R2#\nremove the default route on R1", net)[0]["router"] == "R1"


# ------------------------------------------------------------------------------- what it refuses
@pytest.mark.parametrize("text,why", [
    ("ip route 10.0.7.0 255.255.255.0 R3", "needs a device"),
    ("R1# ip route 10.0.7.0 255.255.255.0", "needs a next hop"),
    ("R1# ip route 10.0.7.0 255.255.255.0 R33", "unknown device R33 (did you mean R3?)"),
    ("R1# ip route 10.0.7.0 255.0.255.0 R3", "not a valid netmask"),
    ("change the route on R1 to R3", "needs a destination"),
    ("send USER traffic on R2 via R3", "only the default route covers it"),  # never edits the default route silently
    ("change the route on R1 for 10.0.5.0/24 via R22", "did you mean R2?"),
    ("route traffic somewhere", "needs a device"),
])
def test_refusals_explain_themselves(net, text, why):
    assert why in reason(text, net)


# ------------------------------------------------------------------------- drafts the engine accepts
@pytest.mark.parametrize("text", [
    "send DB traffic on R1 via R3", "change R1's route for DB from R2 to R3", "remove the default route on R1",
    "set the metric of R1's default route to 50", "R1# ip route 10.0.7.0 255.255.255.0 R3 20",
    "add a route on R3 to USER via R1",
])
def test_drafts_apply_to_the_network(net, text):
    apply_changes(net, [Change.model_validate(c) for c in changes(text, net)])


def test_works_on_generated_networks():
    net = campus_network(3)
    assert changes("send DB1 traffic on R1 via M1", net) == [
        {"operation": "MODIFY_ROUTE", "router": "R1", "destination": "10.1.5.0/24", "new_next_hop": "M1"}]
