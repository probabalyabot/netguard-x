"""ACL rule changes on a device (normally a firewall).

Add a rule; the service, source and destination are optional (missing means any):

    block ssh from USER to DB on FW                   allow https from any to APP on FW at the top
    deny tcp/8080 from 10.0.0.0/24 to DB on FW        permit APP to BACKUP on FW at position 2

Delete a rule by number (counted from 1, as people read an ACL) or by what it does:

    delete rule 2 on FW                               remove the rule on FW that allows APP to DB

A rule needs a device: "deny USER to DB" with no "on FW" is refused with a hint, because as a
requirement it reads "USER must never reach DB" (see policies.py).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .clauses import Clause
from .lexicon import IP, LexError, Lexicon, position_in, rule_number_in, service_in

_ACTIONS = {"allow": "ALLOW", "allows": "ALLOW", "permit": "ALLOW", "permits": "ALLOW",
            "deny": "DENY", "denies": "DENY", "block": "DENY", "blocks": "DENY", "forbid": "DENY", "forbids": "DENY"}
_ACTION = re.compile(r"\b(allow|allows|permit|permits|deny|denies|block|blocks|forbid|forbids)\b", re.I)
_REACH = re.compile(r"\b(reach|reaching|access|talk to|communicate with|connect to)\b")
_DELETE_RULE = re.compile(r"\b(delete|remove|drop)\b.*\brule\b")
_ANY = {"any", "anywhere", "anyone", "everyone", "everything", "all"}
_NEEDS_DEVICE = ("an ACL rule needs a device ('on FW'); for a requirement say "
                 "'USER must never reach DB'")

Result = tuple[Optional[dict], Optional[str]]


def claims(low: str) -> bool:
    """Deleting a rule, or an allow / deny sentence that is not a reachability requirement (those
    say "reach", "access", ...) unless it names the device the rule goes on."""
    if _DELETE_RULE.search(low):
        return True
    if not _ACTION.search(low):
        return False
    return not _REACH.search(low) or bool(re.search(r"\b(on|at)\s+\S+", low))


def parse(clause: Clause, lex: Lexicon) -> Result:
    t = clause.text.strip()
    try:
        ch, why = _delete(t, clause, lex) if _DELETE_RULE.search(t.lower()) else _add(t, clause, lex)
    except LexError as exc:
        ch, why = None, str(exc)
    if ch is None:
        why = lex.unknown_reason(t) or why
    return ch, why


def _device(t: str, clause: Clause, lex: Lexicon) -> Optional[str]:
    return lex.after(t, "on|at") or lex.inherited(clause.device, t)


def _endpoint(t: str, word: str, lex: Lexicon) -> Optional[str]:
    """What follows ``word`` ("from" / "to"): "any", a prefix or address, or a device id."""
    m = re.search(rf"\b{word}\s+(?:the\s+)?(\S+)", t, re.I)
    if not m:
        return None
    token = m.group(1).strip(",.;").lower()
    if token in _ANY:
        return "any"
    p = re.match(rf"({IP}(?:/\d{{1,2}})?)", m.group(1))
    if p and "/" in p.group(1):
        return p.group(1)
    return lex.after(t, word)


def _add(t: str, clause: Clause, lex: Lexicon) -> Result:
    node = _device(t, clause, lex)
    if node is None:
        return None, _NEEDS_DEVICE
    action = _ACTIONS[_ACTION.search(t).group(1).lower()]
    source = _endpoint(t, "from", lex)
    destination = _endpoint(t, "to", lex) or "any"
    if source is None:
        # no "from": "permit APP to BACKUP" names the source before "to"; "block ssh to DB" names none
        others = [d for d in lex.devices_in(t) if d not in (node, destination)]
        source = others[0] if others else "any"
    rule: dict[str, Any] = {"node": node, "source": source, "destination": destination, "action": action}
    service = service_in(t)
    if service:
        rule["protocol"], port = service
        if port is not None:
            rule["port"] = port
    ch: dict[str, Any] = {"operation": "ADD_ACL_RULE", "rule": rule}
    position = position_in(t)
    if position is not None:
        ch["position"] = position
    return ch, None


def _delete(t: str, clause: Clause, lex: Lexicon) -> Result:
    node = lex.after(t, "on|at|from") or lex.inherited(clause.device, t)
    if node is None:
        return None, "say which device the rule is on ('delete rule 2 on FW')"
    rules = [a for a in lex.net.acls if a.node == node]
    if not rules:
        return None, f"{node} has no ACL rules"
    index = rule_number_in(t)
    if index is not None:
        if index >= len(rules):
            return None, f"{node} has only {len(rules)} rule{'s' if len(rules) != 1 else ''}"
        return {"operation": "DELETE_ACL_RULE", "node": node, "rule_index": index}, None

    # "the rule on FW that allows APP to DB": match an existing rule by what it does
    m = re.search(r"\b(?:that|which)\s+(.*)$", t, re.I)
    if not m or not _ACTION.search(m.group(1)):
        return None, "say which rule: 'rule 2', or 'the rule that allows APP to DB'"
    what = m.group(1)
    action = _ACTIONS[_ACTION.search(what).group(1).lower()]
    named = lex.devices_in(what)
    source = _endpoint(what, "from", lex) or (named[0] if named else None)
    destination = _endpoint(what, "to", lex) or (named[1] if len(named) > 1 else None)
    service = service_in(what)

    def matches(rule) -> bool:
        if rule.action != action:
            return False
        if source and not _same_endpoint(rule.source, source, lex):
            return False
        if destination and not _same_endpoint(rule.destination, destination, lex):
            return False
        return service is None or (rule.protocol, rule.port) == service

    hits = [i for i, rule in enumerate(rules) if matches(rule)]
    if not hits:
        return None, f"no rule on {node} {what.strip()}"
    if len(hits) > 1:
        numbers = ", ".join(f"rule {i + 1}" for i in hits)
        return None, f"{len(hits)} rules on {node} match ({numbers}); say which by number"
    return {"operation": "DELETE_ACL_RULE", "node": node, "rule_index": hits[0]}, None


def _same_endpoint(spec: str, wanted: str, lex: Lexicon) -> bool:
    """A rule's source/destination (device id, address, prefix or 'any') against what was typed."""
    if spec.lower() in _ANY or wanted == "any":
        return spec.lower() in _ANY and wanted == "any"
    return spec == wanted or lex.device(spec) == wanted
