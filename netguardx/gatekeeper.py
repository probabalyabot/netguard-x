"""Gatekeeper: the loop between a command source (an LLM agent) and the network.

The gatekeeper owns the live network model.  Every proposed command is verified against that
model before anything changes:

    SAFE             -> executed and checkpointed
    REVIEW           -> held until a person approves or denies it
    NOT_RECOMMENDED  -> rejected, the live model is untouched

Checkpoints store the inverse of every executed command, so the model can be rolled back.
"Executing" means updating the in-memory model; no device is contacted.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, get_args

from pydantic import BaseModel, Field

from .changes import ChangeError, apply_changes
from .impact import AnalysisOptions, ChangeReport, analyze
from .models import Change, Network, Operation

EXECUTED = "EXECUTED"
HELD = "HELD"
REJECTED = "REJECTED"
INVALID = "INVALID"

# The agent may not edit policies: it could otherwise delete the rule it is about to violate.
AGENT_OPERATIONS = frozenset(get_args(Operation)) - {"ADD_POLICY", "DELETE_POLICY"}

Verifier = Callable[[Network, list[Change], AnalysisOptions], ChangeReport]


def full_verifier(network: Network, changes: list[Change], options: AnalysisOptions) -> ChangeReport:
    """Re-simulate every traffic class in both states."""
    return analyze(network, changes, options)


class Checkpoint(BaseModel):
    seq: int  # position in the current history, starting at 1
    version: int  # model version this command produced
    changes: list[Change]
    inverses: list[Change]
    meta: dict[str, Any] = Field(default_factory=dict)


class Pending(BaseModel):
    id: int
    version: int  # model version the command was verified against
    changes: list[Change]
    report: ChangeReport
    meta: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    outcome: str  # EXECUTED | HELD | REJECTED | INVALID
    reason: str
    version: int  # model version after this decision
    verify_ms: float = 0.0
    tier: str = "full"
    report: Optional[ChangeReport] = None
    checkpoint: Optional[int] = None
    pending_id: Optional[int] = None


class Gatekeeper:
    def __init__(self, network: Network, verifier: Verifier = full_verifier,
                 options: Optional[AnalysisOptions] = None):
        self.network = network.model_copy(deep=True)
        self.verifier = verifier
        self.options = options or AnalysisOptions()
        self.version = 0
        self.checkpoints: list[Checkpoint] = []
        self.pending: dict[int, Pending] = {}
        self._next_pending = 1

    # ----------------------------------------------------------------- proposing
    def propose(self, changes: list[Change], meta: Optional[dict[str, Any]] = None) -> Decision:
        """A command from the agent."""
        blocked = sorted({c.operation for c in changes} - AGENT_OPERATIONS)
        if blocked:
            return Decision(outcome=REJECTED, version=self.version,
                            reason=f"the agent may not change policies ({', '.join(blocked)})")
        return self._propose(changes, meta)

    def propose_as_operator(self, changes: list[Change], meta: Optional[dict[str, Any]] = None) -> Decision:
        """A command from a person.  Still verified, but policy edits are allowed."""
        return self._propose(changes, meta)

    def _propose(self, changes: list[Change], meta: Optional[dict[str, Any]]) -> Decision:
        meta = dict(meta or {})
        if not changes:
            return Decision(outcome=INVALID, version=self.version, reason="the command contains no changes")
        report, error, ms = self._verify(changes)
        if report is None:
            return Decision(outcome=INVALID, version=self.version, reason=error, verify_ms=ms)
        verdict, headline = report.verdict["decision"], report.verdict["headline"]
        if verdict == "NOT_RECOMMENDED":
            return Decision(outcome=REJECTED, version=self.version, reason=headline, verify_ms=ms, report=report)
        if verdict == "REVIEW":
            p = Pending(id=self._next_pending, version=self.version, changes=changes, report=report, meta=meta)
            self._next_pending += 1
            self.pending[p.id] = p
            return Decision(outcome=HELD, version=self.version, reason=headline, verify_ms=ms, report=report,
                            pending_id=p.id)
        cp = self._commit(changes, meta)
        return Decision(outcome=EXECUTED, version=self.version, reason=headline, verify_ms=ms, report=report,
                        checkpoint=cp.seq)

    # ------------------------------------------------------------ human approval
    def approve(self, pending_id: int) -> Decision:
        """Execute a held command.  If the model has moved since it was verified, it is verified
        again first, and a person only ever approves the report for the current model."""
        p = self._take(pending_id)
        report, ms = p.report, 0.0
        if p.version != self.version:
            report, error, ms = self._verify(p.changes)
            if report is None:
                return Decision(outcome=INVALID, version=self.version, verify_ms=ms,
                                reason=f"no longer applies to the current model: {error}")
            verdict, headline = report.verdict["decision"], report.verdict["headline"]
            if verdict == "NOT_RECOMMENDED":
                return Decision(outcome=REJECTED, version=self.version, reason=headline, verify_ms=ms, report=report)
            if verdict == "REVIEW":
                self.pending[p.id] = p.model_copy(update={"version": self.version, "report": report})
                return Decision(outcome=HELD, version=self.version, verify_ms=ms, report=report, pending_id=p.id,
                                reason=f"the model changed since this was reviewed; review again: {headline}")
        cp = self._commit(p.changes, p.meta)
        return Decision(outcome=EXECUTED, version=self.version, reason=report.verdict["headline"], verify_ms=ms,
                        report=report, checkpoint=cp.seq)

    def deny(self, pending_id: int) -> Decision:
        p = self._take(pending_id)
        return Decision(outcome=REJECTED, version=self.version, reason="denied by reviewer", report=p.report)

    # ------------------------------------------------------------------ rollback
    def rollback(self, to_seq: int = 0) -> list[Checkpoint]:
        """Undo every checkpoint after ``to_seq`` (0 restores the initial model).  Returns what was undone."""
        if not 0 <= to_seq <= len(self.checkpoints):
            raise ValueError(f"no checkpoint {to_seq}; history has {len(self.checkpoints)}")
        undone: list[Checkpoint] = []
        while len(self.checkpoints) > to_seq:
            cp = self.checkpoints[-1]
            self.network, _, _ = apply_changes(self.network, list(reversed(cp.inverses)))
            undone.append(self.checkpoints.pop())
        if undone:
            self.version += 1
        return undone

    # ------------------------------------------------------------------ internals
    def _verify(self, changes: list[Change]) -> tuple[Optional[ChangeReport], Optional[str], float]:
        t0 = time.perf_counter()
        try:
            report, error = self.verifier(self.network, changes, self.options), None
        except ChangeError as exc:
            report, error = None, str(exc)
        return report, error, round((time.perf_counter() - t0) * 1000, 3)

    def _commit(self, changes: list[Change], meta: dict[str, Any]) -> Checkpoint:
        self.network, inverses, _ = apply_changes(self.network, changes)
        self.version += 1
        cp = Checkpoint(seq=len(self.checkpoints) + 1, version=self.version, changes=changes,
                        inverses=inverses, meta=meta)
        self.checkpoints.append(cp)
        return cp

    def _take(self, pending_id: int) -> Pending:
        if pending_id not in self.pending:
            raise ValueError(f"no pending command {pending_id}")
        return self.pending.pop(pending_id)
