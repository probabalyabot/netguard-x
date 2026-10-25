"""Score the parser against a phrase file:  python -m netguardx.nlp.score <phrases.json> [--network F]

A phrase file is a JSON list of entries, each one request and what it should become:

    {"text": "block ssh from USER to DB on FW",
     "changes": [{"operation": "ADD_ACL_RULE", "rule": {...}}]}       # expected drafts, in order
    {"text": "USER must never reach DB", "policies": [{...}]}          # expected requirements
    {"text": "make it faster", "unparsed": true, "reason_contains": "not"}   # must be refused

``changes`` and ``policies`` default to none.  An entry passes when the parser drafts exactly the
expected changes and policies and refuses nothing (or, for an ``unparsed`` entry, drafts nothing and
refuses with a reason containing ``reason_contains``).  Changes are compared after schema
validation, so a field left at its default does not count as a difference.

Two rates are printed: **exact** (entries that pass) and **understood** (requests the parser turned
into drafts with nothing refused, right or wrong; refusal entries excluded).  The developer corpus
(tests/nlp_corpus.json) measures coverage of the grammar; a held-out set written by someone who has
not read the grammar measures accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..models import Change, Network, Policy
from . import interpret

DEFAULT_NETWORK = Path(__file__).resolve().parent.parent / "examples" / "basic.json"


def _norm_changes(items: list[dict]) -> list[dict]:
    return [Change.model_validate(c).model_dump(exclude_none=True) for c in items]


def _norm_policies(items: list[dict]) -> list[dict]:
    return [Policy.model_validate(p).model_dump(exclude_none=True) for p in items]


def check(entry: dict[str, Any], net: Network) -> tuple[bool, dict[str, Any]]:
    """Whether the parser handles one entry as expected, and what it produced."""
    r = interpret(entry["text"], net)
    got = {"changes": r["changes"], "policies": r["policies"], "unparsed": r["unparsed"]}
    if entry.get("unparsed"):
        reasons = " | ".join(u["reason"] or "" for u in r["unparsed"])
        ok = not r["changes"] and not r["policies"] and bool(r["unparsed"]) \
            and entry.get("reason_contains", "") in reasons
        return ok, got
    ok = not r["unparsed"] \
        and _norm_changes(r["changes"]) == _norm_changes(entry.get("changes", [])) \
        and _norm_policies(r["policies"]) == _norm_policies(entry.get("policies", []))
    return ok, got


def score(entries: list[dict[str, Any]], net: Network) -> dict[str, Any]:
    misses, exact, requests, understood = [], 0, 0, 0
    for e in entries:
        ok, got = check(e, net)
        exact += ok
        if not e.get("unparsed"):
            requests += 1
            understood += bool(got["changes"] or got["policies"]) and not got["unparsed"]
        if not ok:
            misses.append({"text": e["text"], "expected": {k: e[k] for k in ("changes", "policies", "unparsed") if k in e},
                           "got": got})
    return {"entries": len(entries), "exact": exact, "exact_rate": exact / len(entries) if entries else 0.0,
            "requests": requests, "understood": understood,
            "understood_rate": understood / requests if requests else 0.0, "misses": misses}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m netguardx.nlp.score", description=__doc__.split("\n\n")[0])
    ap.add_argument("phrases", help="JSON list of {text, changes?, policies?, unparsed?, reason_contains?}")
    ap.add_argument("--network", default=str(DEFAULT_NETWORK), help="network the phrases refer to")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)
    net = Network.model_validate(json.loads(Path(args.network).read_text(encoding="utf-8")))
    entries = json.loads(Path(args.phrases).read_text(encoding="utf-8"))
    result = score(entries, net)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"exact:      {result['exact']}/{result['entries']} ({result['exact_rate']:.1%})")
        print(f"understood: {result['understood']}/{result['requests']} requests ({result['understood_rate']:.1%})")
        for m in result["misses"]:
            print(f"\nMISS  {m['text']!r}\n  expected {json.dumps(m['expected'])}\n  got      {json.dumps(m['got'])}")
    return 0 if not result["misses"] else 1


if __name__ == "__main__":
    sys.exit(main())
