"""Typed commands to checked changes: text -> drafts -> gatekeeper.

``drafted`` turns an ``interpret`` result into the changes it describes, in the order they were
written (drafted requirements become ADD_POLICY).  ``Session`` feeds typed commands one line at a
time to a ``Gatekeeper`` with incremental verification, the way an agent's commands would arrive:

- A line is drafted against the *current* live model, so it sees what earlier lines executed.
- A config header (``R1(config)#``, ``R1#``, ``on R1:``) sets the device for the lines after it.
- A line with anything not understood is refused as a whole (NOT UNDERSTOOD); half a command is
  never executed.
- By default the session is the AI agent, so policy edits are refused by the gatekeeper's policy
  lock; ``operator=True`` proposes as a person (policy edits allowed, still verified).
- HELD commands stay held; nothing is approved automatically.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from .gatekeeper import EXECUTED, HELD, INVALID, REJECTED, Gatekeeper
from .incremental import IncrementalVerifier
from .models import Change, Network
from .nlp import interpret
from .nlp.clauses import header_device
from .nlp.lexicon import Lexicon

NOT_UNDERSTOOD = "NOT UNDERSTOOD"
OUTCOMES = (EXECUTED, HELD, REJECTED, INVALID, NOT_UNDERSTOOD)


def drafted(result: dict[str, Any]) -> list[Change]:
    """The changes an ``interpret`` result describes, in sentence order; requirements as ADD_POLICY."""
    out: list[Change] = []
    for m in result.get("matched", []):
        if m["kind"] == "change":
            out.append(Change.model_validate(result["changes"][m["index"]]))
        else:
            out.append(Change(operation="ADD_POLICY", policy=result["policies"][m["index"]]))
    return out


class Session:
    def __init__(self, network: Network, operator: bool = False):
        self.gk = Gatekeeper(network, verifier=IncrementalVerifier())
        self.operator = operator
        self.device: Optional[str] = None  # from the last config header
        self.entries: list[dict[str, Any]] = []

    def feed(self, line: str, number: int) -> Optional[dict[str, Any]]:
        """Handle one typed line.  Returns its log entry, or None for blank, comment and header lines."""
        text = line.strip()
        if not text or text.startswith("#"):
            return None
        dev = header_device(text, Lexicon(self.gk.network).device)
        if dev:
            self.device = dev
        r = interpret(f"on {self.device}:\n{text}" if self.device else text, self.gk.network)
        entry: dict[str, Any] = {"line": number, "text": text,
                                 "understood_as": [m["understood_as"] for m in r["matched"]]}
        if r["unparsed"]:
            entry.update(outcome=NOT_UNDERSTOOD, reason="; ".join(f"'{u['text']}': {u['reason']}" for u in r["unparsed"]))
        elif not r["matched"]:
            return None  # a header or a session-only line ("conf t", "end")
        else:
            changes = drafted(r)
            d = self.gk.propose_as_operator(changes) if self.operator else self.gk.propose(changes)
            entry.update(outcome=d.outcome, reason=d.reason, verify_ms=d.verify_ms)
            if d.pending_id is not None:
                entry["pending_id"] = d.pending_id
            if d.checkpoint is not None:
                entry["checkpoint"] = d.checkpoint
        self.entries.append(entry)
        return entry

    def summary(self) -> dict[str, Any]:
        counts = Counter(e["outcome"] for e in self.entries)
        return {"commands": len(self.entries), **{o: counts.get(o, 0) for o in OUTCOMES},
                "checkpoints": len(self.gk.checkpoints), "model_version": self.gk.version,
                "held": sorted(self.gk.pending), "operator": self.operator}


def format_entry(e: dict[str, Any]) -> str:
    """One readable block per command, plain ASCII so any console shows it."""
    head = f"{e['line']:>3}  {e['outcome']:<15} {e['text']}"
    lines = [head] + [f"       = {u}" for u in e["understood_as"]]
    reason = e.get("reason") or ""
    timing = f" ({e['verify_ms']:.1f} ms)" if "verify_ms" in e else ""
    if reason or timing:
        lines.append(f"       {reason}{timing}")
    return "\n".join(lines)
