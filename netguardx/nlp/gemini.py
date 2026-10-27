"""Optional rewrite step before the parser: Gemini restates free text in the phrasings the
rule-based parser reads (see SYNTAX.md).

Off unless ``GEMINI_API_KEY`` is set, in the environment or in a ``.env`` file in the repository
root. ``NETGUARDX_GEMINI=0`` turns it off even with a key. ``GEMINI_MODEL`` picks the model.

The model only rewrites text. Its output goes through ``interpret`` like anything typed, so every
draft is still checked against the network and shown for review. The typed text is parsed first:
Gemini is asked only when something was not understood, and its version is used only when the
parser understands more of it. Any failure (no network, bad key, timeout) falls back to the
parser's own result.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from ..models import Network

log = logging.getLogger("netguardx.gemini")

ROOT = Path(__file__).resolve().parents[2]
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = ("gemini-3.8-flash", "gemini-3.6-flash")  # tried in order; a 404 moves to the next
TIMEOUT_S = 20.0

SYSTEM = """\
You translate network change requests into the exact command syntax of a rule-based parser.
Output only commands this parser understands, one change or requirement per line.

Rules:
- Use device names exactly as listed in the network below (ids, upper case). Map labels, roles,
  addresses and near-misspellings to the right id. Never invent devices.
- A firewall (ACL) rule always needs "on <firewall id>". "via" is only for routes.
- Rule numbers count from 1.
- One change per line. Keep the user's order.
- If a request is ambiguous or cannot be expressed, output it unchanged on its own line.
  Do not guess values the user did not give (no made-up ports, metrics or prefixes), except that
  a route's destination may be a device name (the parser looks up its prefix).

Grammar (square brackets are optional):
  ACL add:      <allow|block> [service] [from <src>] [to <dst>] on <device> [at the top | at position N]
                service: ssh telnet smtp dns http https ntp snmp ldap smb rsync mysql rdp postgres
                redis ping icmp, or tcp/<port>, udp <port>, port <port>. src/dst: device, address,
                CIDR range or any.
  ACL delete:   delete rule <N> on <device>
                remove the rule on <device> that <allows|blocks> <src> to <dst>
  Route add:    add a route on <router> to <prefix|device> via <next hop> [with metric N]
  Route modify: change the route on <router> for <prefix> to <next hop>
                send <device> traffic on <router> via <next hop>
  Route delete: delete the route on <router> for <prefix>
                remove the default route on <router>
  Metric:       set the metric on <router> for <prefix> to <N>
                set the metric of <router>'s default route to <N>
  Cisco lines:  <router>(config)# ip route <network> <netmask> <next hop> [metric]
                <router>(config)# no ip route <network> <netmask> [next hop]
  Link add:     connect <A> and <B> [with cost N]
  Link delete:  remove the link between <A> and <B>
  Requirement:  <src> must reach <dst> [through <device>] [on port N]
                <src> must never reach <dst> [on port N]
  Policy delete: delete policy <id>

Translate Cisco access-list / ACL lines into ACL sentences (e.g. "access-list 101 deny tcp any
host <DB address> eq 22" applied on FW -> "block ssh from any to DB on FW"). Shutting an interface
or link between two devices -> "remove the link between <A> and <B>".

Examples:
  "stop USER from sshing into the database" (firewall FW) -> block ssh from USER to DB on FW
  "let anyone hit the app over https, top priority"      -> allow https from any to APP on FW at the top
  "R1 should send DB stuff through R3 now"               -> send DB traffic on R1 via R3
  "drop R1's default route"                              -> remove the default route on R1
  "get rid of the second firewall rule"                  -> delete rule 2 on FW
  "plug the firewall into BACKUP"                        -> connect FW and BACKUP
  "the internet should never be able to talk to the DB"  -> INET must never reach DB

Reply as JSON: {"lines": ["<command>", ...]}.
"""


def _dotenv() -> dict[str, str]:
    p = ROOT / ".env"
    out: dict[str, str] = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def _setting(name: str) -> str | None:
    return os.environ.get(name) or _dotenv().get(name) or None


def enabled() -> bool:
    return bool(_setting("GEMINI_API_KEY")) and _setting("NETGUARDX_GEMINI") != "0"


def describe_network(net: Network) -> str:
    """The network in a few compact lines: what the model needs to pick the right names."""
    out = ["Devices (id | type | label | addresses):"]
    for n in net.nodes:
        out.append(f"  {n.id} | {n.type} | {n.label or '-'} | {', '.join(n.ip_addresses) or '-'}")
    out.append("Links: " + ", ".join(f"{l.source}-{l.destination}" for l in net.links))
    out.append("Routes:")
    for r in net.routes:
        out.append(f"  on {r.router}: {r.destination} via {r.next_hop} metric {r.metric}")
    rules: dict[str, list[str]] = {}
    for a in net.acls:
        svc = a.protocol + (f"/{a.port}" if a.port is not None else "")
        rules.setdefault(a.node, []).append(f"{a.action} {a.source} -> {a.destination} {svc}")
    out.append("Firewall rules (numbered from 1 on each device):")
    for node, rs in rules.items():
        out += [f"  on {node}: rule {i}: {r}" for i, r in enumerate(rs, 1)]
    if net.policies:
        out.append("Requirements: " + "; ".join(
            f"{p.id}: {p.action} {p.source} -> {p.destination}" for p in net.policies))
    return "\n".join(out)


def _text_of(body: dict[str, Any]) -> str:
    parts = body["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _lines_of(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("```"):  # a fenced reply despite the JSON mime type
        raw = raw.strip("`").removeprefix("json").strip()
    lines = json.loads(raw)["lines"]
    return [str(x).strip() for x in lines if str(x).strip()]


def rewrite(text: str, net: Network) -> str | None:
    """Gemini's restatement of ``text``, one command per line; None when it is off or fails."""
    key = _setting("GEMINI_API_KEY")
    if not key:
        return None
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": f"Network:\n{describe_network(net)}\n\nRequest:\n{text}"}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "required": ["lines"],
                               "properties": {"lines": {"type": "ARRAY", "items": {"type": "STRING"}}}},
        },
    }
    chosen = _setting("GEMINI_MODEL")
    for model in ((chosen,) if chosen else MODELS):
        try:
            r = httpx.post(API.format(model=model), json=payload, timeout=TIMEOUT_S,
                           headers={"x-goog-api-key": key})
            if r.status_code == 404 and not chosen:
                continue
            r.raise_for_status()
            lines = _lines_of(_text_of(r.json()))
            return "\n".join(lines) if lines else None
        except Exception as e:  # never let the rewrite break drafting
            log.warning("Gemini rewrite failed with %s: %s", model, type(e).__name__)
            return None
    return None


def _score(r: dict[str, Any]) -> tuple[int, int]:
    return len(r["unparsed"]), -len(r.get("matched", []))


def interpret(text: str, net: Network) -> dict[str, Any]:
    """``nlp.interpret``, with Gemini's restatement used when the parser understands it better.
    Adds ``rewritten``: the text that was parsed when it is not the typed text, else None."""
    from . import interpret as parse

    typed = parse(text, net)
    if not typed["unparsed"] or not enabled():
        return {**typed, "rewritten": None}
    better = rewrite(text, net)
    if not better or better.strip() == text.strip():
        return {**typed, "rewritten": None}
    r = parse(better, net)
    if _score(r) < _score(typed):
        return {**r, "rewritten": better}
    return {**typed, "rewritten": None}
