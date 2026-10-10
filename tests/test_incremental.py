"""The incremental verifier must return exactly what full verification returns."""
import random

import pytest

from netguardx import AnalysisOptions, Change, ChangeError, Gatekeeper, IncrementalVerifier, analyze, apply_changes
from netguardx.eval.commands import generate_commands
from netguardx.eval.topologies import campus_network
from netguardx.gatekeeper import HELD
from netguardx.network import NetworkState

from conftest import load_change

EXAMPLES = ["route-via-r3", "route-loop", "remove-r1-r2", "open-firewall", "backup-link", "safe-metric"]


def same(a, b):
    """Reports are equal apart from timing and the count of re-simulated classes."""
    if a is None or b is None:
        return a is b
    return a.model_dump(exclude={"meta"}) == b.model_dump(exclude={"meta"})


@pytest.mark.parametrize("name", EXAMPLES)
def test_matches_full_on_the_examples(net, name):
    inc = IncrementalVerifier()
    for opts in (AnalysisOptions(), AnalysisOptions(probes=False), AnalysisOptions(probe_limit=7)):
        assert same(inc(net, load_change(name), opts), analyze(net, load_change(name), opts))


def test_matches_full_on_batches_and_invalid_commands(net):
    inc = IncrementalVerifier()
    batch = load_change("route-via-r3") + load_change("safe-metric") + load_change("backup-link")
    assert same(inc(net, batch, AnalysisOptions()), analyze(net, batch, AnalysisOptions()))
    with pytest.raises(ChangeError):
        inc(net, [Change(operation="DELETE_ROUTE", router="R1", destination="192.0.2.0/24")], AnalysisOptions())
    assert same(inc(net, load_change("route-loop"), AnalysisOptions()), analyze(net, load_change("route-loop")))


@pytest.mark.parametrize("name", EXAMPLES)
def test_shared_counterfactual_and_derived_state_match_fresh_ones(net, name):
    before = net.model_dump()
    fresh_net, fresh_inv, effects = apply_changes(net, load_change(name))
    shared_net, shared_inv, _ = apply_changes(net, load_change(name), share=True)
    assert shared_net == fresh_net and shared_inv == fresh_inv and net.model_dump() == before

    fresh = NetworkState(fresh_net)
    derived = NetworkState(net).derive(shared_net, {n for e in effects for n in e.nodes})
    for n in (x.id for x in net.nodes):
        assert derived.adj.get(n, {}) == fresh.adj.get(n, {})
        assert derived.routes.get(n, []) == fresh.routes.get(n, [])
        assert derived.acls.get(n, []) == fresh.acls.get(n, [])


def test_cache_is_carried_forward_not_rebuilt():
    verifier = IncrementalVerifier()
    gk = Gatekeeper(campus_network(3), verifier=verifier, options=AnalysisOptions(rollback=False))
    for cmd in generate_commands(gk.network, 60, seed=5):
        d = gk.propose(cmd.changes)
        if d.outcome == HELD:
            gk.approve(d.pending_id)
    # the cache moves forward on the next verification, so the last execution may not be counted yet
    assert verifier.builds == 1 and verifier.advances >= len(gk.checkpoints) - 1 > 10
    gk.rollback(0)  # the model jumps somewhere the cache cannot follow
    gk.propose([Change(operation="CHANGE_METRIC", router="M0", destination="0.0.0.0/0", new_metric=3)])
    assert verifier.builds == 2


def test_only_traffic_crossing_a_touched_device_is_resimulated():
    net = campus_network(4)
    inc = IncrementalVerifier()
    # M0 is the side router no traffic uses
    idle = inc(net, [Change(operation="CHANGE_METRIC", router="M0", destination="0.0.0.0/0", new_metric=3)],
               AnalysisOptions())
    assert idle.meta["resimulated"] == 0 and idle.verdict["decision"] == "SAFE"
    # R0's route to its own database subnet only carries traffic for DB0
    local = [Change(operation="MODIFY_ROUTE", router="R0", destination="10.0.5.0/24", new_next_hop="M0")]
    r = inc(net, local, AnalysisOptions())
    assert 0 < r.meta["resimulated"] < r.meta["classes"] / 4
    assert same(r, analyze(net, local))


def _operator_change(rng, gk, step):
    """Policy and ACL edits: the ones that add or remove traffic classes."""
    ends = [n.id for n in gk.network.nodes if n.type in ("host", "server", "internet")]
    kind = rng.choice(["add_policy", "delete_policy", "acl_port", "delete_acl"])
    if kind == "add_policy":
        s, d = rng.sample(ends, 2)
        return Change(operation="ADD_POLICY", policy={"source": s, "destination": d, "protocol": "TCP",
                                                      "port": 8000 + step, "action": rng.choice(["ALLOW", "DENY"])})
    if kind == "delete_policy" and gk.network.policies:
        return Change(operation="DELETE_POLICY", policy_id=rng.choice(gk.network.policies).id)
    fw = rng.choice([n.id for n in gk.network.nodes if n.type == "firewall"])
    if kind == "delete_acl":
        return Change(operation="DELETE_ACL_RULE", node=fw, rule_index=0)
    return Change(operation="ADD_ACL_RULE", rule={"node": fw, "protocol": "UDP", "port": 5000 + step,
                                                  "action": "ALLOW"})


@pytest.mark.parametrize("sites,opts", [
    (0, AnalysisOptions()),  # 0 = the built-in three-tier example
    (3, AnalysisOptions(rollback=False)),
    (3, AnalysisOptions(probe_limit=40)),  # the probe cap changes which classes exist
    (5, AnalysisOptions(probes=False)),
])
def test_gatekeepers_stay_identical_over_a_long_session(net, sites, opts):
    start = net if sites == 0 else campus_network(sites)
    full = Gatekeeper(start, options=opts)
    inc = Gatekeeper(start, verifier=IncrementalVerifier(), options=opts)
    rng = random.Random(sites)
    stream = generate_commands(start, 120, seed=11 + sites, fault_rate=0.4)

    for i, cmd in enumerate(stream):
        if i % 7 == 3:
            changes, propose = [_operator_change(rng, full, i)], "propose_as_operator"
        elif i % 10 == 9:
            changes, propose = cmd.changes + stream[i - 1].changes, "propose"  # a two-change batch
        else:
            changes, propose = cmd.changes, "propose"
        a, b = getattr(full, propose)(changes), getattr(inc, propose)(changes)
        assert a.outcome == b.outcome and same(a.report, b.report), f"step {i}: {changes}"
        if a.outcome == HELD:
            if rng.random() < 0.7:
                a, b = full.approve(a.pending_id), inc.approve(b.pending_id)
            else:
                a, b = full.deny(a.pending_id), inc.deny(b.pending_id)
            assert a.outcome == b.outcome
        if i % 25 == 24 and full.checkpoints:
            to = rng.randrange(len(full.checkpoints))
            full.rollback(to), inc.rollback(to)
        assert full.network == inc.network and full.version == inc.version
    assert full.checkpoints  # the session did execute commands
