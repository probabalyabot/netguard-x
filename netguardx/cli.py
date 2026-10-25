"""Command line interface:  python -m netguardx <command>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .changes import ChangeError
from .impact import AnalysisOptions, analyze
from .models import Change, Network
from .report import render_markdown
from .risk import RiskWeights
from .verify import verify_network

EXIT_OK, EXIT_UNSAFE, EXIT_ERROR = 0, 1, 2


def _load_network(path: str) -> Network:
    return Network.model_validate(json.loads(Path(path).read_text()))


def _load_changes(path: str) -> list[Change]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("changes", [data])
    return [Change.model_validate(c) for c in data]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="netguardx", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="check the network as it is today")
    v.add_argument("network")

    a = sub.add_parser("analyze", help="predict the impact of a proposed change (exit 1 if not recommended)")
    a.add_argument("network")
    a.add_argument("change", help="JSON file: a change, a list of changes, or {\"changes\": [...]}")
    a.add_argument("--json", action="store_true", help="print the full JSON report instead of Markdown")
    a.add_argument("--out", help="write the report to this file")
    a.add_argument("--no-probes", action="store_true", help="skip exposure probes (faster on big networks)")
    a.add_argument("--weights", help="JSON object overriding risk weights")

    s = sub.add_parser("serve", help="run the web UI and API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    e = sub.add_parser("eval", help="replay a synthetic command stream through the baselines and the gatekeeper")
    size = e.add_mutually_exclusive_group()
    size.add_argument("--sites", type=int, nargs="+", help="network sizes in sites, e.g. --sites 4 8 16 (default 4)")
    size.add_argument("--devices", type=int, nargs="+",
                      help="network sizes in devices, e.g. --devices 50 63 75 (each rounded up to whole sites)")
    e.add_argument("--users-per-site", type=int, default=1, help="user machines sharing each site's router")
    e.add_argument("--commands", type=int, default=200, help="commands per network")
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--seeds", type=int, nargs="+", help="run every size once per seed; report means with 95%% CIs")
    e.add_argument("--fault-rate", type=float, default=0.3, help="share of commands drawn from fault classes")
    e.add_argument("--no-probes", action="store_true", help="skip exposure probes")
    e.add_argument("--probe-limit", type=int,
                   help="cap exposure probes per check (default: enough to probe every endpoint pair)")
    e.add_argument("--memory", action="store_true", help="also measure the incremental verifier's cache memory")
    e.add_argument("--out", help="directory for summary.json and steps.csv")

    d = sub.add_parser("draft", help="turn typed config changes into checked changes (exit 2 if not all understood)")
    d.add_argument("network")
    d.add_argument("text", nargs="?", help="the change, e.g. \"block ssh from USER to DB on FW\"")
    d.add_argument("--file", help="read the text from a file instead (several lines, Cisco blocks)")
    d.add_argument("--analyze", action="store_true", help="analyse the drafted changes and print the report")
    d.add_argument("--json", action="store_true", help="with --analyze: the full JSON report instead of Markdown")

    se = sub.add_parser("session", help="run typed commands, one per line, through the gatekeeper")
    se.add_argument("network")
    se.add_argument("commands", help="a text file with one command per line, or - to type them")
    se.add_argument("--operator", action="store_true",
                    help="propose as a person (policy edits allowed) instead of as the AI agent")
    se.add_argument("--out", help="write the session log as JSON to this file")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "draft":
            return _draft(args)
        if args.cmd == "session":
            return _session(args)
        if args.cmd == "serve":
            import uvicorn
            uvicorn.run("netguardx.api:app", host=args.host, port=args.port)
            return EXIT_OK
        if args.cmd == "eval":
            from .eval.run import format_summary, run_eval, write_results
            from .eval.topologies import sites_for_devices
            sites = ([sites_for_devices(d, args.users_per_site) for d in args.devices] if args.devices
                     else args.sites or [4])
            result = run_eval(sites, args.commands, args.seed, args.fault_rate, probes=not args.no_probes,
                              seeds=args.seeds, memory=args.memory, users_per_site=args.users_per_site,
                              probe_limit=args.probe_limit)
            print(format_summary(result))
            if args.out:
                print(f"\nwrote {write_results(result, args.out)}")
            return EXIT_OK
        net = _load_network(args.network)
        if args.cmd == "verify":
            rep = verify_network(net)
            print(json.dumps(rep.model_dump(mode="json"), indent=2))
            return EXIT_OK if rep.summary["policies_violated"] == 0 else EXIT_UNSAFE
        weights = RiskWeights(**json.loads(args.weights)) if args.weights else RiskWeights()
        report = analyze(net, _load_changes(args.change),
                         AnalysisOptions(probes=not args.no_probes, weights=weights))
        text = json.dumps(report.model_dump(mode="json"), indent=2) if args.json else render_markdown(report)
        if args.out:
            Path(args.out).write_text(text)
        else:
            print(text)
        return EXIT_UNSAFE if report.verdict["decision"] == "NOT_RECOMMENDED" else EXIT_OK
    except (ChangeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _draft(args) -> int:
    from .nlp import interpret
    from .pipeline import drafted

    if (args.text is None) == (args.file is None):
        raise ValueError("give the change as text or with --file, not both")
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    net = _load_network(args.network)
    r = interpret(text, net)
    if not args.analyze:
        print(json.dumps(r, indent=2))
        return EXIT_OK if r["matched"] and not r["unparsed"] else EXIT_ERROR
    if r["unparsed"] or not r["matched"]:
        for u in r["unparsed"]:
            print(f"not understood: {u['text']!r}: {u['reason']}", file=sys.stderr)
        if not r["matched"] and not r["unparsed"]:
            print("nothing to analyse", file=sys.stderr)
        return EXIT_ERROR
    for m in r["matched"]:
        print(f"understood: {m['text']!r} = {m['understood_as']}", file=sys.stderr)
    report = analyze(net, drafted(r))
    print(json.dumps(report.model_dump(mode="json"), indent=2) if args.json else render_markdown(report))
    return EXIT_UNSAFE if report.verdict["decision"] == "NOT_RECOMMENDED" else EXIT_OK


def _session(args) -> int:
    from .pipeline import Session, format_entry

    session = Session(_load_network(args.network), operator=args.operator)
    interactive = args.commands == "-" and sys.stdin.isatty()
    source = sys.stdin if args.commands == "-" else Path(args.commands).read_text(encoding="utf-8").splitlines()
    print(f"session on {args.network} as {'an operator' if args.operator else 'the AI agent'}"
          + (" (type commands, Ctrl+Z then Enter to finish)" if interactive else ""), flush=True)
    for number, line in enumerate(source, 1):
        entry = session.feed(line, number)
        if entry:
            print(format_entry(entry), flush=True)
    s = session.summary()
    print(f"\n{s['commands']} commands: " + ", ".join(f"{s[o]} {o.lower()}" for o in
                                                    ("EXECUTED", "HELD", "REJECTED", "INVALID", "NOT UNDERSTOOD"))
          + f"; {s['checkpoints']} checkpoints, model version {s['model_version']}"
          + (f"; held: {', '.join(map(str, s['held']))}" if s["held"] else ""))
    if args.out:
        Path(args.out).write_text(json.dumps({"network": args.network, "summary": s, "entries": session.entries},
                                             indent=2), encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
