"""Check drafts against the network before anyone sees them.

Drafts are checked in the order they were written, each on top of the ones before it, so a later
line may use what an earlier one created ("add a route ...; set its metric to 5").  A draft the
engine would refuse (a route that does not exist, a link that is already there) is reported with
the engine's own reason instead of failing later, and the drafts after it are checked without it.
Drafted requirements are checked as ADD_POLICY changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from ..changes import ChangeError, apply_changes
from ..models import Change, Network, Policy


@dataclass
class Draft:
    text: str  # the clause it came from
    kind: str  # "change" or "policy"
    data: dict  # the drafted change, or the drafted policy


def as_change(d: Draft) -> Change:
    if d.kind == "policy":
        return Change(operation="ADD_POLICY", policy=Policy.model_validate(d.data))
    return Change.model_validate(d.data)


def understood_as(d: Draft) -> str:
    """The draft in canonical words, so the reader can check the parser's reading."""
    if d.kind == "policy":
        return "Requirement: " + Policy.model_validate(d.data).describe()
    return Change.model_validate(d.data).describe()


def validate(net: Network, drafts: list[Draft]) -> tuple[list[Draft], list[tuple[Draft, str]]]:
    """(accepted drafts, [(rejected draft, reason)]), both in the original order."""
    accepted: list[Draft] = []
    applied: list[Change] = []
    rejected: list[tuple[Draft, str]] = []
    for d in drafts:
        try:
            change = as_change(d)
            apply_changes(net, applied + [change], share=True)
        except (ChangeError, ValidationError, ValueError) as exc:
            rejected.append((d, _reason(exc)))
            continue
        accepted.append(d)
        applied.append(change)
    return accepted, rejected


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        msg = exc.errors()[0]["msg"]
    else:
        msg = str(exc)
    msg = re.sub(r"^(Value error, |[A-Z_]+: )", "", msg)
    return f"cannot apply to this network: {msg}"


def suggestion_in(reason: Optional[str]) -> Optional[str]:
    """The device named in a "did you mean X?" reason."""
    m = re.search(r"did you mean (\S+?)\?", reason or "")
    return m.group(1) if m else None
