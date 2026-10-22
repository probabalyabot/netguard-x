"""Derived metrics for an evaluation result: per-size overhead and how check time scales with size."""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

GATED = ("full", "incremental")
WEAKER = ("lint", "reachability")
PROJECT_TO = (150, 300)  # devices; always reported as projections, never as measurements


def fit_power_law(xs: list[float], ys: list[float]) -> Optional[dict[str, Any]]:
    """Least-squares fit of y = a * x^b on log-log axes.  None with fewer than two usable points.
    ``r2`` (on the log values) needs three points; with two the line passes through both."""
    pts = [(x, y) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pts) < 2 or len({x for x, _ in pts}) < 2:
        return None
    lx = np.log([x for x, _ in pts])
    ly = np.log([y for _, y in pts])
    b, ln_a = np.polyfit(lx, ly, 1)
    r2 = None
    if len(pts) >= 3:
        resid = ly - (b * lx + ln_a)
        total = ((ly - ly.mean()) ** 2).sum()
        r2 = float(1 - (resid ** 2).sum() / total) if total > 0 else 1.0
    return {"a": float(math.exp(ln_a)), "exponent": float(b), "r2": r2, "points": len(pts)}


def predict(fit: dict[str, Any], x: float) -> float:
    return fit["a"] * x ** fit["exponent"]


def overhead(run: dict[str, Any]) -> dict[str, Any]:
    """What the gatekeeper adds to each command at one network size, and what the weaker checks cost."""
    arms = run["arms"]
    out: dict[str, Any] = {}
    for arm in GATED:
        s = arms.get(arm)
        if not s:
            continue
        out[arm] = {
            "verify_ms_p50": s["check_ms_p50"], "verify_ms_p50_ci95": s.get("check_ms_p50_ci95"),
            "verify_ms_p95": s["check_ms_p95"], "verify_ms_mean": s["check_ms_mean"],
            "commands_per_s": s.get("commands_per_s"), "phases_ms_mean": s.get("phases_ms_mean"),
            "commit_ms_mean": s.get("commit_ms_mean"), "resim_share": s.get("resim_share"),
        }
    if "full" in out and "incremental" in out and out["incremental"]["verify_ms_p50"] > 0:
        out["speedup_p50"] = round(out["full"]["verify_ms_p50"] / out["incremental"]["verify_ms_p50"], 2)
    out["weaker_checks_ms_p50"] = {a: arms[a]["check_ms_p50"] for a in WEAKER if a in arms}
    return out


def scaling(runs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Median check time against device count for each gatekeeper arm, fitted and projected."""
    out: dict[str, Any] = {}
    for arm in GATED:
        pts = [(r["nodes"], r["arms"][arm]["check_ms_p50"]) for r in runs if arm in r["arms"]]
        fit = fit_power_law([p[0] for p in pts], [p[1] for p in pts])
        if fit is None:
            continue
        out[arm] = {
            "measured": [{"devices": x, "ms_p50": y} for x, y in pts],
            "fit": {k: round(v, 4) if isinstance(v, float) else v for k, v in fit.items()},
            "projected": [{"devices": d, "ms_p50": round(predict(fit, d), 2)} for d in PROJECT_TO],
        }
    return out or None
