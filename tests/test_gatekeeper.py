import json

import pytest

from netguardx import Change, Gatekeeper, verify_network
from netguardx.gatekeeper import EXECUTED, HELD, INVALID, REJECTED

from conftest import load_change


def canon(n):
    """Order-insensitive view of links/routes (a restored link is re-appended, order is not semantic)."""
    d = n.model_dump()
    d["links"] = sorted(json.dumps(x, sort_keys=True) for x in d["links"])
    d["routes"] = sorted(json.dumps(x, sort_keys=True) for x in d["routes"])
    return d


def test_safe_command_is_executed_and_checkpointed(net):
    gk = Gatekeeper(net)
    d = gk.propose(load_change("safe-metric"))
    assert d.outcome == EXECUTED and d.checkpoint == 1 and gk.version == 1
    assert next(r for r in gk.network.routes if r.router == "R1" and r.destination == "0.0.0.0/0").metric == 50
    assert net.routes != gk.network.routes  # the caller's network is not the live model


def test_unsafe_command_is_rejected_and_model_untouched(net):
    gk = Gatekeeper(net)
    d = gk.propose(load_change("route-via-r3"))
    assert d.outcome == REJECTED and d.report.verdict["decision"] == "NOT_RECOMMENDED"
    assert gk.version == 0 and not gk.checkpoints and gk.network == net


def test_invalid_command_is_not_an_exception(net):
    gk = Gatekeeper(net)
    d = gk.propose([Change(operation="DELETE_ROUTE", router="R1", destination="192.0.2.0/24")])
    assert d.outcome == INVALID and "no route" in d.reason
    assert gk.propose([]).outcome == INVALID


def test_review_is_held_until_approved(net):
    gk = Gatekeeper(net)
    d = gk.propose(load_change("backup-link"))
    assert d.outcome == HELD and gk.version == 0 and d.pending_id in gk.pending
    done = gk.approve(d.pending_id)
    assert done.outcome == EXECUTED and gk.version == 1 and not gk.pending
    assert any({l.source, l.destination} == {"FW", "BACKUP"} for l in gk.network.links)


def test_denied_command_never_runs(net):
    gk = Gatekeeper(net)
    d = gk.propose(load_change("backup-link"))
    assert gk.deny(d.pending_id).outcome == REJECTED
    assert gk.version == 0 and gk.network == net
    with pytest.raises(ValueError):
        gk.approve(d.pending_id)


def test_stale_approval_is_verified_again(net):
    gk = Gatekeeper(net)
    held = gk.propose(load_change("backup-link"))
    gk.propose(load_change("safe-metric"))  # the model moves on
    again = gk.approve(held.pending_id)
    assert again.outcome == HELD and gk.pending[held.pending_id].version == gk.version == 1
    assert gk.approve(held.pending_id).outcome == EXECUTED


def test_stale_approval_that_no_longer_applies(net):
    gk = Gatekeeper(net)
    first = gk.propose(load_change("backup-link"))
    second = gk.propose(load_change("backup-link"))
    assert gk.approve(first.pending_id).outcome == EXECUTED
    d = gk.approve(second.pending_id)  # the link now exists
    assert d.outcome == INVALID and gk.version == 1


def test_rollback_restores_earlier_models(net):
    gk = Gatekeeper(net)
    gk.propose(load_change("safe-metric"))
    after_first = gk.network.model_copy(deep=True)
    gk.approve(gk.propose(load_change("backup-link")).pending_id)
    assert len(gk.checkpoints) == 2

    assert [c.seq for c in gk.rollback(1)] == [2]
    assert canon(gk.network) == canon(after_first) and gk.version == 3
    gk.rollback(0)
    assert canon(gk.network) == canon(net) and not gk.checkpoints
    assert verify_network(gk.network).summary["policies_violated"] == 0
    with pytest.raises(ValueError):
        gk.rollback(5)


def test_agent_cannot_edit_policies(net):
    gk = Gatekeeper(net)
    remove_p4 = [Change(operation="DELETE_POLICY", policy_id="P4")]
    d = gk.propose(remove_p4 + load_change("route-via-r3"))
    assert d.outcome == REJECTED and "DELETE_POLICY" in d.reason and d.report is None
    assert len(gk.network.policies) == 6
    assert gk.propose_as_operator(remove_p4).outcome == EXECUTED
    assert len(gk.network.policies) == 5
