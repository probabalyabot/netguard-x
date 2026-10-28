"""Splitting free text into the clauses the grammar modules parse one at a time.

Config-style input can name the device once, in a header the following lines inherit:

    R1(config)#              R1#                on R1:              configure R1
    ip route 10.0.7.0 255.255.255.0 R3

A header may also carry a command on the same line (``R1(config)# ip route ...``).  Lines that only
manage a CLI session (``conf t``, ``end``, ``exit``, ``!`` comments) are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ", then" / " and then" first, so the comma rule does not leave "then" at the start of a clause
# "and" splits only before a word that starts a new request ("... on FW and block telnet ..."), so
# "connect R2 and R3" and "between R1 and R2" stay whole
_VERBS = (r"allow|permit|block|deny|forbid|add|remove|delete|drop|connect|disconnect|cable|unplug|"
          r"send|reroute|route|point|change|set|create|make")
_SPLIT = re.compile(r",?\s+(?:and\s+)?then\s+|\.(?=\s|$)|;|,\s*(?:but\s+|and\s+)?|\s+but\s+|"
                    rf"\s+(?i:and)\s+(?=(?i:{_VERBS})\b)")
# "1. ", "2) ", "- ", "* " at the start of a line: list markers, not part of the request
_LIST_MARKER = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*•])\s+")
_PROMPT = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:\(config[^)]*\))?\s*#\s*(.*)$")
_ON_DEVICE = re.compile(r"^\s*on\s+([A-Za-z0-9_.-]+)\s*:\s*(.*)$", re.I)
# "on R1, send ..." : after splitting at the comma, a clause that is only "on <device>" names the
# device for the next clause only (a header with ":" carries on to the following lines)
_ON_ONLY = re.compile(r"^\s*on\s+([A-Za-z0-9_.-]+)\s*$", re.I)
_CONFIGURE = re.compile(r"^\s*(?:configure|config)\s+(?:device\s+)?([A-Za-z0-9_.-]+)\s*$", re.I)
_SESSION_ONLY = re.compile(r"^\s*(?:!.*|conf(?:igure)?\s+t(?:erminal)?|end|exit|write(?:\s+mem(?:ory)?)?)\s*$", re.I)


@dataclass(frozen=True)
class Clause:
    text: str
    device: Optional[str] = None  # from the nearest header above, when the line names none itself


def header_device(line: str, device_of) -> Optional[str]:
    """The device a config header line names (``R1(config)#``, ``R1#``, ``on R1:``, ``configure R1``),
    with or without a command after it; None when the line is not a header."""
    for pattern in (_PROMPT, _ON_DEVICE, _CONFIGURE):
        m = pattern.match(line)
        if m and (dev := device_of(m.group(1))):
            return dev
    return None


def split_clauses(text: str) -> list[str]:
    """Sentence ends (not the dots inside addresses), semicolons, line breaks, commas or "but" that
    join two requests, and "then".  A bare "and" never splits ("connect R2 and R3" is one clause)."""
    return [c.text for c in split(text)]


def split(text: str, device_of=None) -> list[Clause]:
    """Clauses with the device context of config-style headers.  ``device_of(word)`` resolves a header
    word to a device id (None when it is not a device, so the line is read as ordinary text)."""
    resolve = device_of or (lambda word: None)
    out: list[Clause] = []
    context: Optional[str] = None
    for line in text.splitlines():
        if _SESSION_ONLY.match(line):
            continue
        line = _LIST_MARKER.sub("", line, count=1)
        for pattern in (_PROMPT, _ON_DEVICE, _CONFIGURE):
            m = pattern.match(line)
            if m and (dev := resolve(m.group(1))):
                context = dev
                line = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                break
        just_named: Optional[str] = None
        for c in _SPLIT.split(line):
            if not c or not c.strip():
                continue
            if (m := _ON_ONLY.match(c)) and (dev := resolve(m.group(1))):
                just_named = dev
                continue
            out.append(Clause(c, just_named or context))
            just_named = None
    return out
