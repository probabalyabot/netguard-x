import json

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


TIMING = ("check_ms", "commands_per_s", "phases_ms", "commit_ms", "overhead")


def _strip(value):
    """Drop every timing field, at any depth: they differ from run to run."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if not k.startswith(TIMING)}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _without_timing(result):
    for r in result["runs"]:  # full verification still stops at ~1 while it re-simulates everything
        assert all(a["resim_share"] is None or 0 <= a["resim_share"] <= 1 for a in r["arms"].values())
    return _strip(result["runs"]), _strip(result["steps"])


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


def test_several_seeds_are_combined_with_confidence_intervals():
    result = run_eval([2], commands=20, seeds=[1, 2, 3], arms=("none", "incremental"))
    assert result["config"]["seeds"] == [1, 2, 3] and result["config"]["seed"] == 1
    run = result["runs"][0]
    assert [p["seed"] for p in run["per_seed"]] == [1, 2, 3]
    inc = run["arms"]["incremental"]
    singles = [p["arms"]["incremental"] for p in run["per_seed"]]
    assert inc["check_ms_p50"] == pytest.approx(sum(s["check_ms_p50"] for s in singles) / 3, abs=1e-3)
    assert inc["check_ms_p50_ci95"] is not None and inc["check_ms_p50_ci95"] >= 0
    assert inc["mismatches"] == sum(s["mismatches"] for s in singles) == 0
    assert set(inc["phases_ms_mean"]) == {"sync", "apply", "state", "select", "simulate", "assess"}
    assert inc["commands_per_s"] > 0 and inc["commit_ms_mean"] > 0
    assert run["arms"]["none"]["phases_ms_mean"] is None  # no verifier, nothing to break down
    assert {r["seed"] for r in result["steps"]} == {1, 2, 3}


def test_a_single_seed_has_no_interval():
    inc = run_eval([1], commands=10, seed=4, arms=("incremental",))["runs"][0]["arms"]["incremental"]
    assert inc["check_ms_p50_ci95"] is None


@pytest.mark.parametrize("users", [1, 3])
def test_device_counts_match_the_generator(users):
    from netguardx.eval.topologies import devices_in

    for sites in (1, 4, 9, 12):
        assert len(campus_network(sites, users_per_site=users).nodes) == devices_in(sites, users)


def test_sizes_by_device_count():
    from netguardx.eval.topologies import sites_for_devices

    assert [sites_for_devices(d) for d in (50, 63, 75)] == [8, 10, 12]
    assert sites_for_devices(75, users_per_site=4) == 8
    with pytest.raises(ValueError):
        sites_for_devices(10 ** 6)


def test_extra_users_share_the_router_and_are_held_to_policy():
    net = campus_network(2, users_per_site=3)
    users = sorted(n.id for n in net.nodes if n.type == "host")
    assert users == ["USER0", "USER0-1", "USER0-2", "USER1", "USER1-1", "USER1-2"]
    assert {(l.source, l.destination) for l in net.links} >= {("USER0-2", "R0"), ("USER1-1", "R1")}
    assert any(p.source == "USER0-2" and p.action == "DENY" and p.destination == "DB0" for p in net.policies)
    assert verify_network(net).summary["policies_violated"] == 0


def test_cli_accepts_device_counts(tmp_path, capsys):
    from netguardx.cli import main

    assert main(["eval", "--devices", "14", "--commands", "5", "--out", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["config"]["sites"] == [2] and summary["runs"][0]["nodes"] == 14


def test_evaluation_probes_every_endpoint_pair_by_default():
    from netguardx.eval.run import full_probe_limit, probe_count

    net = campus_network(12)  # 76 devices: 2592 probes, more than the engine's default cap of 2000
    assert probe_count(net, 2000) == 2000 < probe_count(net, full_probe_limit(net)) == 2592
    result = run_eval([1], commands=5, arms=("incremental",))
    assert result["config"]["probe_limit"] == "all pairs"
    assert result["runs"][0]["probes"] == probe_count(campus_network(1), 10 ** 9)
    capped = run_eval([1], commands=5, arms=("incremental",), probe_limit=4)
    assert capped["config"]["probe_limit"] == 4 and capped["runs"][0]["probes"] == 4
