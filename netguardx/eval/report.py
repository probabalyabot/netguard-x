"""A readable Markdown report of an evaluation result (written next to summary.json)."""
from __future__ import annotations

from typing import Any, Optional

ARM_LABEL = {"none": "No check", "lint": "Lint", "reachability": "Reachability",
             "full": "Full verification", "incremental": "Incremental verification"}


def _ms(value: Optional[float], ci: Optional[float] = None) -> str:
    if value is None:
        return "n/a"
    return f"{_fmt(value)} ms" if ci is None else f"{_fmt(value)} ms +/- {_fmt(ci, 2)}"


def _fmt(value: float, digits: int = 3) -> str:
    """Three significant figures without scientific notation: 0.0412, 4.12, 41.2, 412, 4,120."""
    return f"{value:,.0f}" if abs(value) >= 10 ** digits else f"{value:.{digits}g}"


def _num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.4g}"


def render_eval_report(result: dict[str, Any]) -> str:
    c = result["config"]
    seeds = c.get("seeds", [c["seed"]])
    L = ["# NetGuard-X evaluation report", "",
         f"{c['commands']} synthetic commands per network, fault rate {c['fault_rate']}, "
         f"probes {'on' if c['probes'] else 'off'}, seed{'s' if len(seeds) > 1 else ''} {', '.join(map(str, seeds))}.",
         ""]
    if len(seeds) > 1:
        L += ["Figures are means over the seeds; +/- is the half-width of a 95% confidence interval.", ""]

    L += ["## Safety", "", "Unsafe commands executed (per network, mean over seeds):", "",
          "| Devices | " + " | ".join(ARM_LABEL[a] for a in c["arms"]) + " |",
          "|---|" + "---|" * len(c["arms"])]
    for r in result["runs"]:
        L.append(f"| {r['nodes']} | " + " | ".join(_num(r["arms"][a]["unsafe_executed"]) for a in c["arms"]) + " |")
    L.append("")

    L += ["## Overhead per command", "",
          "Time the gatekeeper adds to each command before it may run (verification), the time to apply an "
          "executed command to the model (commit), and the cost of the weaker checks for comparison.", "",
          "| Devices | Full p50 | Incremental p50 | Speed-up | Incremental p95 | Re-simulated | Commit | Lint p50 | Reachability p50 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in result["runs"]:
        o = r.get("overhead", {})
        f, i = o.get("full", {}), o.get("incremental", {})
        w = o.get("weaker_checks_ms_p50", {})
        resim = i.get("resim_share")
        cells = [str(r["nodes"]),
                 _ms(f.get("verify_ms_p50"), f.get("verify_ms_p50_ci95")),
                 _ms(i.get("verify_ms_p50"), i.get("verify_ms_p50_ci95")),
                 f"{o['speedup_p50']:.1f}x" if "speedup_p50" in o else "n/a",
                 _ms(i.get("verify_ms_p95")),
                 "n/a" if resim is None else f"{resim:.1%}",
                 _ms(i.get("commit_ms_mean")), _ms(w.get("lint")), _ms(w.get("reachability"))]
        L.append("| " + " | ".join(cells) + " |")
    L.append("")

    for arm in ("incremental", "full"):
        rows = [(r["nodes"], r.get("overhead", {}).get(arm, {}).get("phases_ms_mean")) for r in result["runs"]]
        rows = [(n, p) for n, p in rows if p]
        if not rows:
            continue
        names = list(rows[0][1])
        L += [f"### Where the time goes: {ARM_LABEL[arm].lower()}", "", "Mean milliseconds per command, by step.", "",
              "| Devices | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        L += [f"| {n} | " + " | ".join(f"{p.get(k, 0):.3g}" for k in names) + " |" for n, p in rows]
        L.append("")

    sc = result.get("scaling")
    if sc:
        L += ["## Scaling", "",
              "Median check time against network size, fitted as time = a x devices^b on log-log axes. "
              "Projected rows are extrapolations from the fit, not measurements.", "",
              "| Verifier | Exponent b | R^2 | Measured | Projected |", "|---|---|---|---|---|"]
        for arm, s in sc.items():
            meas = ", ".join(f"{m['devices']} dev: {_fmt(m['ms_p50'])} ms" for m in s["measured"])
            proj = ", ".join(f"{p['devices']} dev: {_fmt(p['ms_p50'])} ms" for p in s["projected"])
            r2 = s["fit"]["r2"]
            L.append(f"| {ARM_LABEL[arm]} | {s['fit']['exponent']:.2f} | {'n/a' if r2 is None else f'{r2:.3f}'} | "
                     f"{meas} | {proj} |")
        L.append("")

    L += ["## Caveats", "",
          "- Times are from one machine and cover verification only; commit time is reported separately.",
          "- \"Unsafe\" is defined by full verification, so the gatekeeper arms are safe by construction.",
          "- Unsafe counts for the weaker checks are undercounts once their network is already broken.",
          "- Projections assume check time keeps growing at the fitted rate; a probe limit that stops "
          "growing with the network would bend the real curve.", ""]
    return "\n".join(L)
