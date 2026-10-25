"""Vocabulary helpers of the parser (netguardx/nlp/lexicon.py), on the built-in three-tier network."""
import pytest

from netguardx.eval.topologies import campus_network
from netguardx.nlp.lexicon import (
    LexError, Lexicon, mask_length, number_after, position_in, prefix_in, rule_number_in, service_in,
)


@pytest.fixture()
def lex(net):
    return Lexicon(net)


# ------------------------------------------------------------------------------------------- devices
@pytest.mark.parametrize("word,device", [
    ("R1", "R1"), ("r1", "R1"), ("fw", "FW"), ("Internet", "INET"), ("the internet", "INET"),
    ("the firewall", "FW"), ("firewall", "FW"), ("10.0.5.10", "DB"), ("10.255.0.3", "R3"),
    ("R9", None), ("10.0.5.11", None), ("router", None),
])
def test_device_by_id_label_role_or_address(lex, word, device):
    assert lex.device(word) == device


def test_devices_in_order_of_appearance_including_addresses(lex):
    assert lex.devices_in("allow 10.0.2.10 to reach the database DB via the firewall") == ["APP", "DB", "FW"]
    assert lex.devices_in("USER then usER then R2") == ["USER", "R2"]  # each device once


def test_an_address_with_a_prefix_or_mask_is_a_destination_not_a_device(lex):
    assert lex.devices_in("route 10.0.5.10/32 on R1") == ["R1"]
    assert lex.devices_in("ip route 10.0.5.10 255.255.255.255 R3") == ["R3"]


def test_role_words_need_exactly_one_device_of_that_type():
    lex = Lexicon(campus_network(3))  # three firewalls
    assert lex.device("the firewall") is None and lex.device("FW1") == "FW1"


def test_hyphenated_names_match_whole():
    lex = Lexicon(campus_network(1, users_per_site=3))
    assert lex.devices_in("connect USER0-2 to R0") == ["USER0-2", "R0"]
    assert lex.device("USER0-2") == "USER0-2" and lex.device("USER0") == "USER0"


# ----------------------------------------------------------------------------------- typo suggestions
@pytest.mark.parametrize("text,unknown", [
    ("route via R22", [("R22", "R2")]),
    ("block ssh on FWW", [("FWW", "FW")]),
    ("from USR to DB", [("USR", "USER")]),
    ("reach SRV9", [("SRV9", None)]),  # name-shaped, nothing close
])
def test_unknown_names_get_the_closest_device(lex, text, unknown):
    assert lex.unknown_names(text) == unknown


def test_vocabulary_and_known_names_are_never_flagged(lex):
    assert lex.unknown_names("Allow TCP and SSH, HTTPS, DNS on the ACL of FW for R1 and DB over IPv4") == []
    assert lex.unknown_names("change the route please") == []  # ordinary lower-case words


# ------------------------------------------------------------------------------- prefixes and masks
@pytest.mark.parametrize("text,prefix", [
    ("route 10.0.5.0/24 via R3", "10.0.5.0/24"),
    ("route 10.0.5.7/24 via R3", "10.0.5.0/24"),  # host bits cleared
    ("ip route 10.0.5.0 255.255.255.0 R3", "10.0.5.0/24"),
    ("ip route 0.0.0.0 0.0.0.0 INET", "0.0.0.0/0"),
    ("host route to 10.0.5.10 via R3", "10.0.5.10/32"),
    ("no prefix here", None),
])
def test_prefix_forms(text, prefix):
    assert prefix_in(text) == prefix


def test_netmasks():
    assert mask_length("255.255.255.0") == 24 and mask_length("255.255.240.0") == 20
    with pytest.raises(LexError):
        mask_length("255.0.255.0")
    with pytest.raises(LexError):
        prefix_in("ip route 10.0.5.0 255.0.255.0 R3")


# ------------------------------------------------------------------------------------------- services
@pytest.mark.parametrize("text,service", [
    ("block ssh", ("TCP", 22)), ("allow HTTPS", ("TCP", 443)), ("dns traffic", ("UDP", 53)),
    ("postgresql", ("TCP", 5432)), ("tcp/8443", ("TCP", 8443)), ("udp 514", ("UDP", 514)),
    ("port 8080", ("TCP", 8080)), ("tcp port 25", ("TCP", 25)), ("ping", ("ICMP", None)),
    ("all udp", ("UDP", None)), ("everything", None),
])
def test_service_forms(text, service):
    assert service_in(text) == service


# -------------------------------------------------------------------------------- positions, numbers
@pytest.mark.parametrize("text,index", [
    ("at the top", 0), ("first", 0), ("at position 1", 0), ("at position 3", 2), ("as rule 2", 1),
    ("at the end", None), ("", None),
])
def test_positions_count_from_one(text, index):
    assert position_in(text) == index


@pytest.mark.parametrize("text,index", [
    ("delete rule 1 on FW", 0), ("delete rule #3 on FW", 2), ("remove the second rule on FW", 1),
    ("remove the rule that allows APP", None),
])
def test_rule_numbers_count_from_one(text, index):
    assert rule_number_in(text) == index


def test_zero_is_not_a_position_or_rule_number():
    with pytest.raises(LexError, match="count from 1"):
        position_in("at position 0")
    with pytest.raises(LexError, match="count from 1"):
        rule_number_in("delete rule 0 on FW")


def test_numbers_after_keywords():
    assert number_after("set the metric of R1's default route to 50", "metric") == 50
    assert number_after("connect R2 and R3 with cost 5", "cost") == 5
    assert number_after("connect R2 and R3", "cost") is None


# ------------------------------------------------------------------------------- covering routes
def test_route_covering_a_device_is_the_most_specific(lex):
    assert lex.route_covering("R1", "DB") == "10.0.5.0/24"  # not R1's default route
    assert lex.route_covering("R1", "USER") == "0.0.0.0/0"  # only the default covers it
    assert lex.route_covering("R2", "BACKUP") == "0.0.0.0/0"
    assert lex.route_covering("USER", "NOPE") is None
