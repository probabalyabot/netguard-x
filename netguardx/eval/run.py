"""Replay one command stream through several gatekeeping strategies and measure each.

Arms:
    none          every applicable command is executed
    lint          rejected only if it introduces a route whose next hop cannot be used
    reachability  rejected only if a flow that was delivered stops being delivered ("is it up?")
    full          the Gatekeeper with full verification; REVIEW commands are held, then approved
    incremental   the same Gatekeeper with the incremental verifier

Ground truth for "unsafe" is the full ``analyze`` verdict against the state the command is
proposed in, so the ``full`` arm is safe by construction.  What the arms are compared on is how
much unsafe configuration the weaker checks let through, and what each check costs in time.
For the gatekeeper arms every report is also compared with that ground-truth report
(``mismatches``), and ``resim_share`` is the fraction of traffic classes that were re-simulated.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..changes import ChangeError, apply_changes
from ..gatekeeper import EXECUTED, HELD, INVALID, REJECTED, Gatekeeper, full_verifier
from ..impact import AnalysisOptions, analyze
from ..incremental import IncrementalVerifier
from ..models import Network
from ..network import NetworkState, static_issues
from ..verify import build_classes, verify_network
from .commands import Command, generate_commands
from .metrics import cache_memory, overhead, scaling
from .report import render_eval_report
from .stats import mean_ci
from .topologies import campus_network

ARMS = ("none", "lint", "reachability", "full", "incremental")


def _delivered(net: Network) -> set[str]:
    return {t.key for t in verify_network(net).traces if t.delivered}


def _lint_ok(before: Network, after: Network) -> bool:
    known = {i.key() for i in static_issues(NetworkState(before))}
    return all(i.key() in known for i in static_issues(NetworkState(after)))


def _reach_ok(before: Network, after: Network) -> bool:
    return _delivered(before) <= _delivered(after)


_CHECKS: dict[str, Optional[Callable[[Network, Network], bool]]] = {
    "none": None, "lint": _lint_ok, "reachability": _reach_ok,
}


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * len(s)))], 3)


def run_arm(arm: str, network: Network, commands: list[Command],
            options: AnalysisOptions) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gk = None
    if arm in ("full", "incremental"):
        verifier = IncrementalVerifier() if arm == "incremental" else full_verifier
        gk = Gatekeeper(network, verifier=verifier, options=options)
    state = network
    required = _delivered(network)  # traffic that worked at the start must keep working
    n = {"executed": 0, "rejected": 0, "held": 0, "invalid": 0,
         "unsafe_executed": 0, "safe_rejected": 0, "unhealthy_steps": 0, "mismatches": 0}
    times: list[float] = []
    shares: list[float] = []
    phases: dict[str, list[float]] = {}
    commits: list[float] = []
    rows: list[dict[str, Any]] = []

    for cmd in commands:
        try:
            oracle = analyze(state, cmd.changes, options)
            verdict = oracle.verdict["decision"]
        except ChangeError:
            oracle, verdict = None, INVALID
        ms, share = 0.0, None
        if gk is not None:
            d = gk.propose(cmd.changes, meta={"intent": cmd.intent})
            if d.report is not None:  # commands that do not apply are not verified, so not timed
                ms, meta = d.verify_ms, d.report.meta
                share = round(meta.get("resimulated", meta["classes"]) / meta["classes"], 4)
                times.append(ms)
                shares.append(share)
                for k, v in meta.get("phases_ms", {}).items():
                    phases.setdefault(k, []).append(v)
            n["mismatches"] += (d.report is None) != (oracle is None) or (
                oracle is not None and d.report.model_dump(exclude={"meta"}) != oracle.model_dump(exclude={"meta"}))
            if d.outcome == HELD:
                n["held"] += 1
                d = gk.approve(d.pending_id)
            if d.outcome == EXECUTED:
                commits.append(d.commit_ms)
            outcome, state = d.outcome, gk.network
        elif verdict == INVALID:
            outcome = INVALID
        else:
            check = _CHECKS[arm]
            t0 = time.perf_counter()
            after = apply_changes(state, cmd.changes)[0]
            ok = check is None or check(state, after)
            if check is not None:
                ms = round((time.perf_counter() - t0) * 1000, 3)
                times.append(ms)
            outcome = EXECUTED if ok else REJECTED
            if ok:
                state = after

        unsafe = verdict == "NOT_RECOMMENDED"
        n[outcome.lower()] += 1
        n["unsafe_executed"] += outcome == EXECUTED and unsafe
        n["safe_rejected"] += outcome == REJECTED and not unsafe
        rep = verify_network(state)
        healthy = rep.summary["policies_violated"] == 0 and required <= {t.key for t in rep.traces if t.delivered}
        n["unhealthy_steps"] += not healthy
        rows.append({"arm": arm, "step": cmd.step, "intent": cmd.intent, "operation": cmd.changes[0].operation,
                     "oracle": verdict, "outcome": outcome, "check_ms": ms, "resim_share": share,
                     "healthy": healthy})

    mean_ms = round(sum(times) / len(times), 3) if times else 0.0
    summary = {"commands": len(commands), **n,
               "resim_share": round(sum(shares) / len(shares), 4) if shares else None,
               "check_ms_mean": mean_ms, "check_ms_p50": _pct(times, 0.5), "check_ms_p95": _pct(times, 0.95),
               "commands_per_s": round(1000 / mean_ms, 1) if mean_ms > 0 else None,
               "phases_ms_mean": {k: round(sum(v) / len(v), 3) for k, v in phases.items()} if phases else None,
               "commit_ms_mean": round(sum(commits) / len(commits), 3) if commits else None}
    return summary, rows


_CI_KEYS = ("check_ms_mean", "check_ms_p50", "check_ms_p95", "commands_per_s")


def aggregate(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine one arm's summaries over several seeds: means, a 95% CI for the timing keys, and the
    total of ``mismatches`` (a correctness count, so any non-zero seed must show)."""
    out: dict[str, Any] = {}
    for key, first in summaries[0].items():
        vals = [s[key] for s in summaries if s.get(key) is not None]
        if key == "mismatches":
            out[key] = sum(vals)
        elif vals and isinstance(vals[0], dict):
            names = sorted({k for v in vals for k in v})
            out[key] = {k: round(mean_ci([v[k] for v in vals if k in v])[0], 3) for k in names}
        elif vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            m, half = mean_ci(vals)
            out[key] = round(m, 4)
            if key in _CI_KEYS:
                out[f"{key}_ci95"] = round(half, 4) if half is not None else None
        else:
            out[key] = first
    return out


def probe_count(net: Network, limit: int) -> int:
    """Exposure probes one check of ``net`` simulates under ``limit``."""
    return sum(1 for c in build_classes([net], probes=True, probe_limit=limit).values() if not c.declared)


def full_probe_limit(net: Network) -> int:
    """A probe limit that covers every endpoint pair on every service of ``net``, with room for a
    command that introduces one more service (at most as many probes again)."""
    return 2 * probe_count(net, 10 ** 9)


def run_eval(sites: list[int], commands: int = 200, seed: int = 0, fault_rate: float = 0.3,
             probes: bool = True, arms: tuple[str, ...] = ARMS,
             seeds: Optional[list[int]] = None, memory: bool = False,
             users_per_site: int = 1, probe_limit: Optional[int] = None) -> dict[str, Any]:
    """Run every arm on every size.  With several ``seeds`` each size is replayed once per seed and
    the per-arm summaries are combined by ``aggregate``; ``per_seed`` keeps the individual ones."""
    seeds = list(seeds) if seeds else [seed]
    runs: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for size in sites:
        net = campus_network(size, users_per_site=users_per_site)
        limit = probe_limit if probe_limit is not None else full_probe_limit(net)
        options = AnalysisOptions(probes=probes, probe_limit=limit, rollback=False)  # one change per command
        per_seed = []
        for s in seeds:
            stream = generate_commands(net, commands, seed=s, fault_rate=fault_rate)
            results = {}
            for arm in arms:
                results[arm], rows = run_arm(arm, net, stream, options)
                steps += [{"sites": size, "seed": s, **r} for r in rows]
            per_seed.append({"seed": s, "arms": results})
        arm_summaries = {arm: aggregate([p["arms"][arm] for p in per_seed]) for arm in arms}
        run = {"sites": size, "nodes": len(net.nodes), "links": len(net.links), "routes": len(net.routes),
               "probes": probe_count(net, limit) if probes else 0,
               "flows": len(net.flows), "policies": len(net.policies), "arms": arm_summaries,
               "per_seed": per_seed}
        run["overhead"] = overhead(run)
        if memory:
            run["memory"] = cache_memory(net, options)
        runs.append(run)
    return {"config": {"sites": sites, "commands": commands, "seed": seeds[0], "seeds": seeds,
                       "fault_rate": fault_rate, "probes": probes, "arms": list(arms), "memory": memory,
                       "users_per_site": users_per_site,
                       "probe_limit": "all pairs" if probe_limit is None else probe_limit},
            "runs": runs, "scaling": scaling(runs), "steps": steps}


def write_results(result: dict[str, Any], out_dir: str) -> Path:
    """summary.json (everything but the per-step rows), steps.csv and a readable report.md."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {k: v for k, v in result.items() if k != "steps"}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_eval_report(result), encoding="utf-8")
    with (out / "steps.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(result["steps"][0]) if result["steps"] else ["sites"])
        w.writeheader()
        w.writerows(result["steps"])
    return out


def format_summary(result: dict[str, Any]) -> str:
    c = result["config"]
    seeds = c.get("seeds", [c["seed"]])
    seed_txt = f"seed {seeds[0]}" if len(seeds) == 1 else f"seeds {', '.join(map(str, seeds))} (means, +/- 95% CI)"
    L = [f"{c['commands']} commands per network, {seed_txt}, fault rate {c['fault_rate']}, "
         f"probes {'on' if c['probes'] else 'off'}", ""]
    head = ("sites", "nodes", "arm", "executed", "rejected", "held", "invalid", "unsafe_exec", "safe_rej",
            "unhealthy", "mismatch", "resim", "p50_ms", "p95_ms")
    L.append("  ".join(f"{h:>12}" for h in head))
    for run in result["runs"]:
        for arm, s in run["arms"].items():
            gated = s["resim_share"] is not None
            counts = [f"{s[k]:.4g}" for k in ("executed", "rejected", "held", "invalid",
                                                "unsafe_executed", "safe_rejected", "unhealthy_steps")]
            vals = (run["sites"], run["nodes"], arm, *counts,
                    s["mismatches"] if gated else "-", f"{s['resim_share']:.1%}" if gated else "-",
                    _with_ci(s, "check_ms_p50"), _with_ci(s, "check_ms_p95"))
            L.append("  ".join(f"{v:>12}" for v in vals))
    return "\n".join(L)


def _with_ci(s: dict[str, Any], key: str) -> str:
    half = s.get(f"{key}_ci95")
    return f"{s[key]:.3g}" if half is None else f"{s[key]:.3g}+/-{half:.2g}"
