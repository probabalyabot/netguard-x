"""Per-step timing: recorded in meta and on decisions, never part of what a report says."""
from netguardx import AnalysisOptions, Gatekeeper, IncrementalVerifier, analyze
from netguardx.gatekeeper import EXECUTED, REJECTED

from conftest import load_change

FULL_PHASES = {"apply", "state", "classes", "simulate", "assess"}
INC_PHASES = {"sync", "apply", "state", "select", "simulate", "assess"}


def test_full_verification_records_its_phases(net):
    r = analyze(net, load_change("route-via-r3"), AnalysisOptions(rollback=False))
    phases = r.meta["phases_ms"]
    assert set(phases) == FULL_PHASES and all(v >= 0 for v in phases.values())
    # the phases cover the whole call; duration_ms is taken just before assess finishes
    assert sum(phases.values()) >= r.meta["duration_ms"]


def test_incremental_verification_records_its_phases(net):
    inc = IncrementalVerifier()
    r = inc(net, load_change("route-via-r3"), AnalysisOptions(rollback=False))
    assert set(r.meta["phases_ms"]) == INC_PHASES and all(v >= 0 for v in r.meta["phases_ms"].values())
    full = analyze(net, load_change("route-via-r3"), AnalysisOptions(rollback=False))
    assert r.model_dump(exclude={"meta"}) == full.model_dump(exclude={"meta"})


def test_decisions_report_commit_time_only_when_executed(net):
    gk = Gatekeeper(net, verifier=IncrementalVerifier())
    done = gk.propose(load_change("safe-metric"))
    assert done.outcome == EXECUTED and done.commit_ms > 0 and done.verify_ms > 0
    rejected = gk.propose(load_change("route-via-r3"))
    assert rejected.outcome == REJECTED and rejected.commit_ms == 0
    approved = gk.approve(gk.propose(load_change("backup-link")).pending_id)
    assert approved.outcome == EXECUTED and approved.commit_ms > 0
