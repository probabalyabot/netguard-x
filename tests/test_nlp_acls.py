"""ACL rule and link changes (netguardx/nlp/acls.py, links.py), on the three-tier network.

FW's rules there: 1. ALLOW APP -> DB tcp/5432, 2. ALLOW DB -> BACKUP tcp/873, 3. DENY DB -> INET.
"""
import json
from pathlib import Path

import pytest

from netguardx import Change, apply_changes
from netguardx.nlp import interpret

SCRIPTS = Path(__file__).parent.parent / "test-scripts"


def changes(text, net):
    r = interpret(text, net)
    assert not r["unparsed"], r["unparsed"]
    return r["changes"]


def reason(text, net):
    r = interpret(text, net)
    assert not r["changes"] and len(r["unparsed"]) == 1, r
    return r["unparsed"][0]["reason"]


def rule(**kw):
    return {"operation": "ADD_ACL_RULE", "rule": {"node": "FW", **kw}}


# ------------------------------------------------------------------------------------------ add
@pytest.mark.parametrize("text,expected", [
    ("block ssh from USER to DB on FW", rule(source="USER", destination="DB", action="DENY", protocol="TCP", port=22)),
    ("allow https from any to APP on FW at the top",
     {**rule(source="any", destination="APP", action="ALLOW", protocol="TCP", port=443), "position": 0}),
    ("permit APP to BACKUP on FW at position 2", {**rule(source="APP", destination="BACKUP", action="ALLOW"), "position": 1}),
    ("block ssh to DB on the firewall", rule(source="any", destination="DB", action="DENY", protocol="TCP", port=22)),
    ("deny tcp/8080 from 10.0.0.0/24 to DB on FW",
     rule(source="10.0.0.0/24", destination="DB", action="DENY", protocol="TCP", port=8080)),
    ("deny dns from 10.0.0.10 to everyone on FW", rule(source="USER", destination="any", action="DENY", protocol="UDP", port=53)),
    ("FW#\nblock ping from INET to APP", rule(source="INET", destination="APP", action="DENY", protocol="ICMP")),
])
def test_adding_rules(net, text, expected):
    assert changes(text, net) == [expected]


# --------------------------------------------------------------------------------------- delete
@pytest.mark.parametrize("text,index", [
    ("delete rule 2 on FW", 1), ("remove rule #1 from FW", 0), ("delete the third rule on FW", 2),
    ("remove the rule on FW that allows APP to DB", 0),
    ("remove the rule on FW that permits rsync from DB to BACKUP", 1),
    ("drop the rule on FW which denies DB to the internet", 2),
])
def test_deleting_rules(net, text, index):
    assert changes(text, net) == [{"operation": "DELETE_ACL_RULE", "node": "FW", "rule_index": index}]


# ----------------------------------------------------------------------------------------- links
@pytest.mark.parametrize("text,expected", [
    ("connect R2 and R3 with cost 5", {"operation": "ADD_LINK", "node_a": "R2", "node_b": "R3", "cost": 5}),
    ("cable the firewall to BACKUP", {"operation": "ADD_LINK", "node_a": "FW", "node_b": "BACKUP"}),
    ("disconnect R1 from R2", {"operation": "DELETE_LINK", "node_a": "R1", "node_b": "R2"}),
    ("remove the link between 10.255.0.2 and FW", {"operation": "DELETE_LINK", "node_a": "R2", "node_b": "FW"}),
])
def test_links(net, text, expected):
    assert changes(text, net) == [expected]


# ------------------------------------------------------------------------------------ refusals
@pytest.mark.parametrize("text,why", [
    ("deny USER to DB", "needs a device ('on FW')"),
    ("delete rule 9 on FW", "FW has only 3 rules"),
    ("delete rule 0 on FW", "count from 1"),
    ("remove the rule on FW that allows USER to DB", "no rule on FW allows USER to DB"),
    ("delete rule 1 on R1", "R1 has no ACL rules"),
    ("block ssh from USER to DB on FWW", "did you mean FW?"),
    ("connect R2 and R33", "did you mean R3?"),
])
def test_refusals_explain_themselves(net, text, why):
    assert why in reason(text, net)


def test_requirements_are_not_mistaken_for_acl_rules(net):
    r = interpret("USER must never reach DB", net)
    assert not r["changes"] and r["policies"][0]["action"] == "DENY"


# --------------------------------------------------------------------- same as the demo scripts
@pytest.mark.parametrize("text,script", [
    ("allow everything from any to any on FW at the top", "fail-05-open-firewall"),
    ("block postgres from APP to DB on FW at the top", "fail-06-block-app-database"),
    ("deny postgres from USER to DB on FW", "pass-04-explicit-firewall-deny"),
])
def test_sentences_give_the_demo_scripts_changes(net, text, script):
    expected = json.loads((SCRIPTS / f"{script}.json").read_text(encoding="utf-8"))["changes"]
    drafted = [Change.model_validate(c) for c in changes(text, net)]
    assert drafted == [Change.model_validate(c) for c in expected]


@pytest.mark.parametrize("text", [
    "block ssh from USER to DB on FW", "allow https from any to APP on FW at the top", "delete rule 2 on FW",
    "remove the rule on FW that allows APP to DB", "connect R2 and R3 with cost 5", "disconnect R1 from R2",
])
def test_drafts_apply_to_the_network(net, text):
    apply_changes(net, [Change.model_validate(c) for c in changes(text, net)])


@pytest.mark.parametrize("text, said", [
    ("allow ssh from USER to the moon on FW", "to the moon"),
    ("allow everything from the car park to DB on FW", "from the car park"),
    ("block ssh from USER to the database on FW", "to the database"),
])
def test_an_endpoint_that_is_not_understood_is_refused_not_read_as_any(net, text, said):
    # it used to become "any": an allow rule far wider than what was typed
    assert f"'{said}'" in reason(text, net)


def test_the_before_an_endpoint_is_skipped(net):
    assert changes("block ssh from the internet to DB on FW", net) == [
        rule(source="INET", destination="DB", action="DENY", protocol="TCP", port=22)]
