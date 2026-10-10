import pytest

from netguardx import verify_network
from netguardx.eval.commands import BENIGN, FAULTS, generate_commands
from netguardx.eval.run import run_eval, write_results
from netguardx.eval.topologies import campus_network


@pytest.mark.parametrize("sites", [1, 2, 5, 9])
def test_campus_network_starts_clean(sites):
    net = campus_network(sites)
    assert len([n for n in net.nodes if n.type == "firewall"]) == sites
    assert all(n.x is not None and n.y is not None for n in net.nodes)
    assert verify_network(net).summary["policies_violated"] == 0


def test_campus_network_rejects_bad_sizes():
    with pytest.raises(ValueError):
        campus_network(0)


def test_command_stream_is_seeded(net):
    a = generate_commands(net, 50, seed=3)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in generate_commands(net, 50, seed=3)]
    assert [c.model_dump() for c in a] != [c.model_dump() for c in generate_commands(net, 50, seed=4)]
    assert {c.intent for c in a} <= set(BENIGN) | set(FAULTS)
    assert all(c.intent in BENIGN for c in generate_commands(net, 20, seed=3, fault_rate=0))


def _without_timing(result):
    runs = [{**r, "arms": {a: {k: v for k, v in s.items() if not k.startswith("check_ms")}
                           for a, s in r["arms"].items()}} for r in result["runs"]]
    steps = [{k: v for k, v in s.items() if k != "check_ms"} for s in result["steps"]]
    for r in runs:  # full verification still stops at ~1 while it re-simulates everything
        assert all(a["resim_share"] is None or 0 <= a["resim_share"] <= 1 for a in r["arms"].values())
    return runs, steps


def test_arms_and_reproducibility(tmp_path):
    result = run_eval([2], commands=100, seed=1)
    arms = result["runs"][0]["arms"]
    # the gatekeeper never executes an unsafe command and never leaves the network unhealthy
    assert arms["full"]["unsafe_executed"] == 0 and arms["full"]["unhealthy_steps"] == 0
    # executing everything does both, and an "is it up?" check still lets unsafe commands through
    assert arms["none"]["unsafe_executed"] > 0 and arms["none"]["unhealthy_steps"] > 0
    assert arms["reachability"]["unsafe_executed"] > 0
    # incremental verification reaches the same decisions as full, re-simulating less
    inc = arms["incremental"]
    assert inc["mismatches"] == 0 and arms["full"]["mismatches"] == 0
    assert {k: inc[k] for k in ("executed", "rejected", "held", "invalid")} == \
           {k: arms["full"][k] for k in ("executed", "rejected", "held", "invalid")}
    assert inc["resim_share"] < 0.5 and arms["full"]["resim_share"] == 1
    for s in arms.values():
        assert s["executed"] + s["rejected"] + s["invalid"] == s["commands"] == 100

    assert _without_timing(run_eval([2], commands=100, seed=1)) == _without_timing(result)

    out = write_results(result, tmp_path)
    assert (out / "summary.json").exists()
    assert len((out / "steps.csv").read_text().splitlines()) == 1 + len(arms) * 100
