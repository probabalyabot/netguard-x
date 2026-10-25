"""Natural language -> structured intent (rule-based).

This is the seam where an LLM belongs.  The contract is the same either way: free text goes in,
*structured, schema-validated* changes or policies come out, and a person reviews them before
the deterministic engine runs.  The model never decides whether a change is safe.

The rule-based parser handles a set of phrasings, one module per kind of change.  Anything it
does not recognise is returned in ``unparsed`` rather than guessed at.

    clauses.py   split the text into clauses
    lexicon.py   device names and address patterns
    links.py     add / remove a link
    routes.py    add / delete / modify a route, change a metric
    policies.py  reachability requirements, drafted as policies
"""
from __future__ import annotations

from typing import Any

from ..models import Network
from . import links, policies, routes
from .clauses import split_clauses
from .lexicon import node_lookup

_NOT_A_CHANGE = "not a route or link change"


def _parse_change(clause: str, lookup: dict[str, str]) -> tuple[dict | None, str | None]:
    t = clause.strip()
    low = t.lower()
    if links.claims(low):
        return links.parse(t, lookup)
    if routes.claims(low):
        return routes.parse(t, lookup)
    return None, _NOT_A_CHANGE


def interpret(text: str, net: Network) -> dict[str, Any]:
    lookup = node_lookup(net)
    changes: list[dict] = []
    drafted_policies: list[dict] = []
    unparsed: list[dict] = []
    for clause in split_clauses(text):
        ch, why_c = _parse_change(clause, lookup)
        if ch:
            changes.append(ch)
            continue
        pol, why_p = policies.parse(clause, lookup)
        if pol:
            drafted_policies.append(pol)
            continue
        unparsed.append({"text": clause.strip(), "reason": why_c if why_c != _NOT_A_CHANGE else why_p})
    kind = "changes" if changes and not drafted_policies else "requirements" if drafted_policies and not changes else \
        "mixed" if changes and drafted_policies else "unknown"
    return {
        "parser": "rule-based",
        "kind": kind,
        "changes": changes,
        "policies": drafted_policies,
        "unparsed": unparsed,
        "needs_review": True,
        "note": "Review the structured result before analysing. This parser only understands simple "
                "route, link and reachability phrasings.",
    }
