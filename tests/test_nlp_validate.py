"""Drafts checked against the network, the sentence-to-change mapping, and policy deletion."""
from netguardx.nlp import interpret


def test_a_draft_that_cannot_apply_is_reported_with_the_engines_reason(net):
    r = interpret("delete the route on R1 for 10.9.0.0/24", net)
    assert r["changes"] == [] and r["unparsed"] == [{
        "text": "delete the route on R1 for 10.9.0.0/24",
        "reason": "cannot apply to this network: R1 has no route 10.9.0.0/24"}]


def test_later_lines_see_what_earlier_lines_created(net):
    r = interpret("add a route on R1 for 10.0.9.0/24 via R2; set the metric on R1 for 10.0.9.0/24 to 5", net)
    assert [c["operation"] for c in r["changes"]] == ["ADD_ROUTE", "CHANGE_METRIC"] and not r["unparsed"]


def test_later_lines_see_what_earlier_lines_removed(net):
    r = interpret("cable FW to BACKUP. add a link between FW and BACKUP", net)
    assert len(r["changes"]) == 1 and "already exists" in r["unparsed"][0]["reason"]


def test_a_rejected_draft_does_not_stop_the_ones_after_it(net):
    r = interpret("delete the route on R1 for 10.9.0.0/24; remove the default route on R1", net)
    assert r["changes"] == [{"operation": "DELETE_ROUTE", "router": "R1", "destination": "0.0.0.0/0"}]
    assert len(r["unparsed"]) == 1


def test_unparsed_keeps_the_order_the_sentences_were_written_in(net):
    r = interpret("make it faster; delete the route on R1 for 10.9.0.0/24; route traffic somewhere", net)
    assert [u["text"] for u in r["unparsed"]] == [
        "make it faster", "delete the route on R1 for 10.9.0.0/24", "route traffic somewhere"]


def test_matched_maps_each_sentence_to_its_change_in_plain_words(net):
    r = interpret("USER must never reach APP. send DB traffic on R1 via R3\nblock ssh from USER to DB on FW", net)
    assert [(m["kind"], m["index"]) for m in r["matched"]] == [("policy", 0), ("change", 0), ("change", 1)]
    assert [m["understood_as"] for m in r["matched"]] == [
        "Requirement: DENY USER -> APP TCP",
        "Modify route on R1: 10.0.5.0/24 next hop -> R3",
        "Add ACL rule on FW: DENY USER -> DB TCP port 22",
    ]
    for m in r["matched"]:  # index points at the draft in its list
        assert (r["changes"] if m["kind"] == "change" else r["policies"])[m["index"]]


def test_a_misspelt_device_carries_a_suggestion(net):
    [u] = interpret("block ssh from USER to DB on FWW", net)["unparsed"]
    assert u["suggestion"] == "FW" and "did you mean FW?" in u["reason"]
    [u] = interpret("make it faster", net)["unparsed"]
    assert "suggestion" not in u


def test_deleting_a_policy(net):
    assert interpret("delete policy P3", net)["changes"] == [{"operation": "DELETE_POLICY", "policy_id": "P3"}]
    assert interpret("remove the requirement p4", net)["changes"] == [{"operation": "DELETE_POLICY", "policy_id": "P4"}]
    [u] = interpret("delete policy P9", net)["unparsed"]
    assert u["reason"] == "no policy P9 (policies: P1, P2, P3, P4, P5, P6)"


def test_requirements_are_checked_too(net):
    r = interpret("APP must reach DB through FW on port 5432", net)
    assert r["policies"] and r["matched"][0]["kind"] == "policy" and not r["unparsed"]


def test_a_deleted_rule_reads_back_with_the_number_that_was_typed(net):
    """Rule numbers count from 1 when typed and when read back; only rule_index is 0-based."""
    [m] = interpret("delete rule 2 on FW", net)["matched"]
    assert m["understood_as"] == "Delete ACL rule 2 on FW"


def test_and_before_a_new_request_splits_it_so_no_rule_is_lost(net):
    """Found 2026-10-28: the first of two rules joined by "and" was dropped without an error."""
    r = interpret("block ssh from USER to DB on FW and block telnet from USER to DB on FW", net)
    assert [c["rule"]["port"] for c in r["changes"]] == [22, 23] and not r["unparsed"]
    r = interpret("connect R2 and R3 AND send DB traffic on R1 via R3", net)
    assert [c["operation"] for c in r["changes"]] == ["ADD_LINK", "MODIFY_ROUTE"]


def test_and_between_devices_still_does_not_split(net):
    assert interpret("connect R2 and R3", net)["changes"] == [
        {"operation": "ADD_LINK", "node_a": "R2", "node_b": "R3"}]
    assert len(interpret("remove the link between R1 and R2", net)["changes"]) == 1


def test_list_markers_are_ignored(net):
    r = interpret("1. block ssh from USER to DB on FW\n2) delete rule 1 on FW\n- connect R2 and R3", net)
    assert len(r["matched"]) == 3 and not r["unparsed"]


def test_on_device_comma_names_the_device_like_on_device_colon(net):
    r = interpret("on R1, send traffic for DB via R3. On FW, block ssh from USER to DB", net)
    assert [m["understood_as"] for m in r["matched"]] == [
        "Modify route on R1: 10.0.5.0/24 next hop -> R3", "Add ACL rule on FW: DENY USER -> DB TCP port 22"]
