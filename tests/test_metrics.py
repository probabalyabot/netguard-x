import json

import pytest

from netguardx.eval.metrics import fit_power_law, overhead, predict, scaling
from netguardx.eval.run import run_eval, write_results


def test_power_law_fit_recovers_a_known_curve():
    xs = [10, 20, 40, 80]
    fit = fit_power_law(xs, [2 * x ** 1.5 for x in xs])
    assert fit["exponent"] == pytest.approx(1.5) and fit["a"] == pytest.approx(2)
    assert fit["r2"] == pytest.approx(1.0) and fit["points"] == 4
    assert predict(fit, 160) == pytest.approx(2 * 160 ** 1.5)


def test_power_law_fit_needs_two_distinct_sizes_and_r2_needs_three():
    assert fit_power_law([10], [5]) is None
    assert fit_power_law([10, 10], [5, 6]) is None
    assert fit_power_law([10, 20], [0, 0]) is None  # zero times (no check) cannot be fitted
    two = fit_power_law([10, 20], [1, 4])
    assert two["exponent"] == pytest.approx(2) and two["r2"] is None


def _run(nodes, full, inc):
    arm = lambda ms: {"check_ms_p50": ms, "check_ms_p95": ms * 2, "check_ms_mean": ms}  # noqa: E731
    return {"nodes": nodes, "arms": {"full": arm(full), "incremental": arm(inc), "lint": arm(1.0)}}


def test_overhead_and_scaling_from_runs():
    runs = [_run(10, 8.0, 2.0), _run(20, 32.0, 4.0), _run(40, 128.0, 8.0)]
    o = overhead(runs[0])
    assert o["speedup_p50"] == 4 and o["weaker_checks_ms_p50"] == {"lint": 1.0}
    assert o["incremental"]["verify_ms_p95"] == 4.0
    sc = scaling(runs)
    assert sc["full"]["fit"]["exponent"] == pytest.approx(2) and sc["incremental"]["fit"]["exponent"] == pytest.approx(1)
    assert [p["devices"] for p in sc["incremental"]["projected"]] == [150, 300]
    assert sc["incremental"]["projected"][0]["ms_p50"] == pytest.approx(30, rel=1e-3)  # 0.2 ms per device


def test_a_real_run_writes_overhead_scaling_and_a_report(tmp_path):
    result = run_eval([1, 2], commands=15, seed=2, arms=("lint", "full", "incremental"))
    for r in result["runs"]:
        assert r["overhead"]["speedup_p50"] > 0
        assert set(r["overhead"]["incremental"]["phases_ms_mean"]) >= {"simulate", "assess"}
    assert set(result["scaling"]) == {"full", "incremental"}
    out = write_results(result, tmp_path)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert "scaling" in summary and "steps" not in summary
    report = (out / "report.md").read_text(encoding="utf-8")
    for heading in ("## Safety", "## Overhead per command", "### Where the time goes", "## Scaling", "## Caveats"):
        assert heading in report
