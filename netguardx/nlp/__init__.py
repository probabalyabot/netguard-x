"""Natural language -> structured intent (rule-based).

This is the seam where an LLM belongs.  The contract is the same either way: free text goes in,
*structured, schema-validated* changes or policies come out, and a person reviews them before
the deterministic engine runs.  The model never decides whether a change is safe.

The rule-based parser handles a set of phrasings, one module per kind of change.  Anything it
does not recognise is returned in ``unparsed`` rather than guessed at.

    clauses.py   split the text into clauses; device context from config-style headers
    lexicon.py   devices, addresses, prefixes, services, numbers, typo suggestions
    acls.py      add / delete an ACL rule
    links.py     add / remove a link
    routes.py    add / delete / modify a route, change a metric; Cisco ``ip route`` lines
    policies.py  reachability requirements (drafted as policies); deleting a policy
    validate.py  drafts checked against the network, in order
"""
from __future__ import annotations

from typing import Any

from ..models import Network
from . import acls, links, policies, routes
from .clauses import Clause, split
from .lexicon import Lexicon
from .validate import Draft, suggestion_in, understood_as, validate

_NOT_A_CHANGE = "not a route or link change"


def _parse_change(clause: Clause, lex: Lexicon) -> tuple[dict | None, str | None]:
    """Policy deletion and ACL rules first: ACL sentences use "from", "to" and device names like
    routes and links do."""
    low = clause.text.strip().lower()
    if policies.claims_delete(low):
        return policies.parse_delete(clause.text, lex.net)
    if acls.claims(low):
        return acls.parse(clause, lex)
    if links.claims(low):
        return links.parse(clause, lex)
    if routes.claims(low):
        return routes.parse(clause, lex)
    return None, _NOT_A_CHANGE


def _draft(clause: Clause, lex: Lexicon) -> tuple[Draft | None, str | None]:
    text = clause.text.strip()
    ch, why_c = _parse_change(clause, lex)
    if ch:
        return Draft(text, "change", ch), None
    pol, why_p = policies.parse(clause.text, lex.names)
    if pol:
        return Draft(text, "policy", pol), None
    return None, why_c if why_c != _NOT_A_CHANGE else why_p


def interpret(text: str, net: Network) -> dict[str, Any]:
    """Draft changes and requirements from ``text`` and check them against ``net``.

    Returns ``changes`` and ``policies`` (the drafts that apply), ``unparsed`` (clauses not
    understood or not applicable, each with a ``reason`` and, for a misspelt device, a
    ``suggestion``), and ``matched``: for each accepted draft, its clause, ``kind``, its ``index``
    in ``changes`` or ``policies``, and ``understood_as``, the draft in canonical words."""
    lex = Lexicon(net)
    drafts: list[Draft] = []
    failed: dict[int, tuple[str, str]] = {}  # clause position -> (text, reason)
    position: dict[int, int] = {}  # id(draft) -> clause position
    for i, clause in enumerate(split(text, lex.device)):
        d, why = _draft(clause, lex)
        if d is None:
            failed[i] = (clause.text.strip(), why)
        else:
            position[id(d)] = i
            drafts.append(d)

    accepted, rejected = validate(net, drafts)
    for d, why in rejected:
        failed[position[id(d)]] = (d.text, why)

    changes = [d.data for d in accepted if d.kind == "change"]
    drafted_policies = [d.data for d in accepted if d.kind == "policy"]
    matched, counters = [], {"change": 0, "policy": 0}
    for d in accepted:
        matched.append({"text": d.text, "kind": d.kind, "index": counters[d.kind], "understood_as": understood_as(d)})
        counters[d.kind] += 1
    unparsed = []
    for _, (clause_text, why) in sorted(failed.items()):
        item: dict[str, Any] = {"text": clause_text, "reason": why}
        if (s := suggestion_in(why)):
            item["suggestion"] = s
        unparsed.append(item)

    kind = "changes" if changes and not drafted_policies else "requirements" if drafted_policies and not changes else \
        "mixed" if changes and drafted_policies else "unknown"
    return {
        "parser": "rule-based",
        "kind": kind,
        "changes": changes,
        "policies": drafted_policies,
        "unparsed": unparsed,
        "matched": matched,
        "needs_review": True,
        "note": "Review the structured result before analysing. This parser understands route changes "
                "(plain English or Cisco ip route lines), links, ACL rules and reachability "
                "requirements.",
    }
