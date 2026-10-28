"""Optional rewrite step before the parser: a language model restates free text in the phrasings
the rule-based parser reads (see SYNTAX.md).

Providers are tried in order (``LLM_ORDER``, default ``ollama,gemini``):

- **ollama**: a local model (``OLLAMA_MODEL``, at ``OLLAMA_HOST``). No internet or quota.
  Skipped quickly when Ollama is not running.
- **gemini**: Google's API, when ``GEMINI_API_KEY`` is set. ``GEMINI_MODEL`` puts a model first.

Settings come from the environment or a ``.env`` file in the repository root.
``NETGUARDX_LLM=0`` turns the step off.

The model only rewrites text. Its output goes through ``interpret`` like anything typed, so every
draft is still checked against the network and shown for review. The typed text is parsed first:
a model is asked only when something was not understood, and its version is used only when the
parser understands more of it. Any failure falls back to the parser's own result.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from ..models import Network

log = logging.getLogger("netguardx.llm")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORDER = "ollama,gemini"

OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.1:8b"  # tested against qwen2.5-coder:7b: more faithful to meaning
# A cold start loads the model into the GPU first, so the read timeout is long. The connect timeout
# is short: on Windows a refused local connection is retried for about 2 s before failing.
OLLAMA_TIMEOUT = httpx.Timeout(30.0, connect=0.5)
# The enterprise network's summary is longer than Ollama's default context. Loading with a different
# num_ctx makes Ollama reload the model, so the warm-up must use this same value.
OLLAMA_OPTIONS = {"temperature": 0, "num_ctx": 8192}

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tried in order. A model that is missing, busy, failing or slow moves on to the next one.
# Each model has its own rate limit, so a 429 is worth trying elsewhere.
GEMINI_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash")
RETRY_STATUS = {404, 408, 429, 500, 502, 503, 504}
GEMINI_TIMEOUT_S = 12.0  # per model
GEMINI_DEADLINE_S = 30.0  # for all Gemini models together
# Rewriting is easy: minimal thinking answers in about 2 s instead of 4. 3.7+ refuse "minimal".
THINKING = {"gemini-3.8-flash": "low", "gemini-3.7-flash": "low"}

SCHEMA = {"type": "object", "required": ["lines"],
          "properties": {"lines": {"type": "array", "items": {"type": "string"}}}}
_cache: dict[tuple[str, int], tuple[str, str]] = {}  # (text, network) -> (rewrite, provider)

SYSTEM = """\
You translate network change requests into the exact command syntax of a rule-based parser.
Output only commands this parser understands, one change or requirement per line.

Rules:
- Use device names exactly as listed in the network below (ids, upper case). Map labels, roles,
  addresses and near-misspellings to the right id. Never invent devices.
- A firewall (ACL) rule always needs "on <firewall id>". "via" is only for routes.
- Rule numbers count from 1.
- One change per line. Keep the user's order.
- Never invent a change. If a request names no concrete change ("make it faster", "fix the
  network", "hello"), is ambiguous, names a device that is not in the network with no clear
  match, or cannot be expressed in the grammar, output it unchanged on its own line.
- Do not guess values the user did not give (no made-up ports, metrics or prefixes), except that
  a route's destination may be a device name (the parser looks up its prefix).
- Write every line exactly in one of the grammar forms below, in plain words. Never use arrows,
  "->", "ANY" as a service, or JSON inside a line. To cover all traffic, leave the service out.
- A request about a group of devices ("the guest laptops") becomes one line per device.
- "should never be able to reach / talk to" is a requirement ("<src> must never reach <dst>");
  "block", "stop", "deny" and "don't let" are firewall rules on a firewall between the two.

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

Examples (request, then the line to output), for a network whose firewall is FW:
  "stop USER from sshing into the database"
      block ssh from USER to DB on FW
  "let anyone hit the app over https, top priority"
      allow https from any to APP on FW at the top
  "R1 should send DB stuff through R3 now"
      send DB traffic on R1 via R3
  "drop R1's default route"
      remove the default route on R1
  "get rid of the second firewall rule"
      delete rule 2 on FW
  "plug the firewall into BACKUP"
      connect FW and BACKUP
  "the internet should never be able to talk to the DB"
      INET must never reach DB
  "make it faster"
      make it faster
  "can you secure the app server"   (says what to achieve, not which change: never guess one)
      can you secure the app server

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
    return _setting("NETGUARDX_LLM") != "0"


def describe_network(net: Network) -> str:
    """The network in a few compact lines: what the model needs to pick the right names."""
    out = ["Devices (id | type | label | addresses):"]
    for n in net.nodes:
        out.append(f"  {n.id} | {n.type} | {n.label or '-'} | {', '.join(n.ip_addresses) or '-'}")
    out.append("Links: " + ", ".join(f"{l.source}-{l.destination}" for l in net.links))
    out.append("Routes:")
    for r in net.routes:
        out.append(f"  on {r.router}: {r.destination} via {r.next_hop} metric {r.metric}")
    # Written in the parser's own words, so the model does not copy a notation it cannot read.
    rules: dict[str, list[str]] = {}
    for a in net.acls:
        svc = "" if a.protocol.upper() == "ANY" else f" {a.protocol.lower()}" + (f"/{a.port}" if a.port is not None else "")
        verb = "allow" if a.action == "ALLOW" else "block"
        rules.setdefault(a.node, []).append(f"{verb}{svc} from {a.source} to {a.destination}")
    out.append("Firewall rules (numbered from 1 on each device):")
    for node, rs in rules.items():
        out += [f"  on {node}: rule {i}: {r}" for i, r in enumerate(rs, 1)]
    if net.policies:
        out.append("Requirements:")
        out += [f"  {p.id}: {p.source} must {'reach' if p.action == 'ALLOW' else 'never reach'} {p.destination}"
                for p in net.policies]
    return "\n".join(out)


def _lines_of(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("```"):  # a fenced reply despite asking for JSON
        raw = raw.strip("`").removeprefix("json").strip()
    lines = json.loads(raw)["lines"]
    return [str(x).strip() for x in lines if str(x).strip()]


def _ollama_url(path: str) -> str:
    return f"{(_setting('OLLAMA_HOST') or OLLAMA_HOST).rstrip('/')}{path}"


def _ask_ollama(request: str) -> list[str] | None:
    model = _setting("OLLAMA_MODEL") or OLLAMA_MODEL
    try:
        r = httpx.post(_ollama_url("/api/chat"), timeout=OLLAMA_TIMEOUT, json={
            "model": model, "stream": False, "format": SCHEMA, "keep_alive": "60m",
            "options": OLLAMA_OPTIONS,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": request}],
        })
        r.raise_for_status()
        return _lines_of(r.json()["message"]["content"])
    except (httpx.ConnectError, httpx.ConnectTimeout):
        log.info("Ollama is not running; skipping it")
    except Exception as e:  # never let the rewrite break drafting
        log.warning("Ollama %s failed: %s", model, type(e).__name__)
    return None


def _ask_gemini(request: str) -> list[str] | None:
    key = _setting("GEMINI_API_KEY")
    if not key:
        return None
    chosen = _setting("GEMINI_MODEL")
    models = (chosen, *[m for m in GEMINI_MODELS if m != chosen]) if chosen else GEMINI_MODELS
    start = time.monotonic()
    for model in models:
        left = GEMINI_DEADLINE_S - (time.monotonic() - start)
        if left < 2:
            break
        try:
            r = httpx.post(GEMINI_API.format(model=model), timeout=min(GEMINI_TIMEOUT_S, left),
                           headers={"x-goog-api-key": key}, json={
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": request}]}],
                "generationConfig": {
                    "thinkingConfig": {"thinkingLevel": THINKING.get(model, "minimal")},
                    "responseMimeType": "application/json", "responseSchema": SCHEMA,
                },
            })
            if r.status_code in RETRY_STATUS:
                log.warning("Gemini %s answered %s; trying the next model", model, r.status_code)
                continue
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return _lines_of("".join(p.get("text", "") for p in parts if not p.get("thought")))
        except httpx.TimeoutException:
            log.warning("Gemini %s timed out; trying the next model", model)
        except Exception as e:  # never let the rewrite break drafting; try the next model
            log.warning("Gemini %s failed: %s", model, type(e).__name__)
    return None


PROVIDERS: dict[str, Callable[[str], list[str] | None]] = {"ollama": _ask_ollama, "gemini": _ask_gemini}


def providers() -> list[str]:
    order = (_setting("LLM_ORDER") or DEFAULT_ORDER).replace(" ", "").lower().split(",")
    return [p for p in order if p in PROVIDERS]


def rewrite(text: str, net: Network, provider: str) -> str | None:
    """``provider``'s restatement of ``text``, one command per line; None when it fails.
    Answers are remembered, so drafting the same text again gives the same result."""
    context = describe_network(net)
    key = (provider, text.strip(), hash(context))
    if key not in _cache:
        lines = PROVIDERS[provider](f"Network:\n{context}\n\nRequest:\n{text}")
        if not lines:
            return None
        _cache[key] = "\n".join(lines)
    return _cache[key]


def _score(r: dict[str, Any]) -> tuple[int, int]:
    return len(r["unparsed"]), -len(r.get("matched", []))


def interpret(text: str, net: Network) -> dict[str, Any]:
    """``nlp.interpret``, with a model's restatement used when the parser understands it better.
    Providers are asked in order until one's version is fully understood. Adds ``rewritten`` (the
    text that was parsed, when it is not the typed text) and ``rewritten_by`` (the provider)."""
    from . import interpret as parse

    best = {**parse(text, net), "rewritten": None, "rewritten_by": None}
    if not best["unparsed"] or not enabled():
        return best
    for name in providers():
        better = rewrite(text, net, name)
        if not better or better.strip() == text.strip():
            continue
        r = parse(better, net)
        if _score(r) < _score(best):
            best = {**r, "rewritten": better, "rewritten_by": name}
        if not best["unparsed"]:
            break
    return best


def warm_up() -> None:
    """Load the Ollama model into memory so the first draft is not slow. Errors are ignored."""
    if not enabled() or "ollama" not in providers():
        return
    try:
        httpx.post(_ollama_url("/api/generate"), timeout=OLLAMA_TIMEOUT, json={
            "model": _setting("OLLAMA_MODEL") or OLLAMA_MODEL, "keep_alive": "60m", "options": OLLAMA_OPTIONS})
    except Exception:
        pass
