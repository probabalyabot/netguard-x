"""Vocabulary shared by the grammar modules: device names, addresses, prefixes, services and numbers."""
from __future__ import annotations

import difflib
import ipaddress
import re
from typing import Optional

from ..models import Network

CIDR = r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?"


def node_lookup(net: Network) -> dict[str, str]:
    """Lower-cased names a device can be called by (id, label, "internet") -> device id."""
    m = {n.id.lower(): n.id for n in net.nodes}
    for n in net.nodes:
        if n.label:
            m.setdefault(n.label.lower(), n.id)
    internet = next((n.id for n in net.nodes if n.type == "internet"), None)
    if internet:
        m.setdefault("internet", internet)
        m.setdefault("the internet", internet)
    return m


def nodes_in(text: str, lookup: dict[str, str]) -> list[str]:
    """Node ids in order of appearance."""
    found: list[tuple[int, str]] = []
    for name, nid in lookup.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I):
            found.append((m.start(), nid))
    found.sort()
    out: list[str] = []
    for _, nid in found:
        if nid not in out:
            out.append(nid)
    return out


def after(text: str, words: str, lookup: dict[str, str], last: bool = False):
    """The device named right after one of ``words`` (a regex alternation), first or last occurrence."""
    names = "|".join(sorted((re.escape(k) for k in lookup), key=len, reverse=True))
    hits = re.findall(rf"\b(?:{words})\s+({names})(?![\w-])", text, re.I)
    if not hits:
        return None
    return lookup[(hits[-1] if last else hits[0]).lower()]


# --------------------------------------------------------------------------------------------------
# Richer vocabulary (used by the grammar modules from the next steps on)


class LexError(ValueError):
    """Text that names something the parser cannot accept (a bad netmask, rule number 0, ...)."""


IP = r"\d{1,3}(?:\.\d{1,3}){3}"

# Well-known services: name -> (protocol, port).  Port None means "every port of that protocol".
SERVICES: dict[str, tuple[str, Optional[int]]] = {
    "ssh": ("TCP", 22), "telnet": ("TCP", 23), "smtp": ("TCP", 25), "dns": ("UDP", 53),
    "http": ("TCP", 80), "ntp": ("UDP", 123), "snmp": ("UDP", 161), "ldap": ("TCP", 389),
    "https": ("TCP", 443), "smb": ("TCP", 445), "rsync": ("TCP", 873), "mysql": ("TCP", 3306),
    "rdp": ("TCP", 3389), "postgres": ("TCP", 5432), "postgresql": ("TCP", 5432), "redis": ("TCP", 6379),
    "icmp": ("ICMP", None), "ping": ("ICMP", None),
}

# Capitalised words that look like device names but are vocabulary, never devices.
_STOP = {"TCP", "UDP", "ICMP", "ACL", "ACLS", "IP", "IPV4", "IPV6", "CIDR", "NAT", "VLAN", "BGP", "OSPF",
         "LAN", "WAN", "DMZ", "API", "CLI", "JSON", "OK", "AND", "OR", "NOT", "NO", "ANY", "ALL", "THE"}
_STOP |= {s.upper() for s in SERVICES}
_NAME_SHAPED = re.compile(r"(?<![\w.-])([A-Za-z][A-Za-z_]*\d+[\w-]*|[A-Z]{2,}[\w-]*)(?![\w.-])")
_ROLE_TYPES = {"firewall": "firewall", "internet": "internet"}  # role word -> device type


def mask_length(mask: str) -> int:
    """255.255.255.0 -> 24.  Masks with gaps (255.0.255.0) are rejected."""
    try:
        return ipaddress.ip_network(f"0.0.0.0/{mask}").prefixlen
    except ValueError as exc:
        raise LexError(f"{mask} is not a valid netmask") from exc


def prefix_in(text: str) -> Optional[str]:
    """The first destination prefix written in ``text``: CIDR, address + netmask, or a bare address
    (a /32).  Host bits are cleared: 10.0.5.7/24 -> 10.0.5.0/24."""
    m = re.search(rf"({IP})(?:\s*/\s*(\d{{1,2}})|\s+(255(?:\.\d{{1,3}}){{3}}|0\.0\.0\.0))?(?![\d.])", text)
    if not m:
        return None
    addr, length, mask = m.groups()
    bits = int(length) if length is not None else mask_length(mask) if mask else 32
    try:
        return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))
    except ValueError as exc:
        raise LexError(f"{addr}/{bits} is not a valid prefix") from exc


def service_in(text: str) -> Optional[tuple[str, Optional[int]]]:
    """Protocol and port: "tcp/443", "udp 53", "port 8080" (TCP), or a service name ("ssh")."""
    low = text.lower()
    m = re.search(r"\b(tcp|udp)\s*[/:]?\s*(?:port\s*)?(\d{1,5})\b", low)
    if m:
        return m.group(1).upper(), int(m.group(2))
    m = re.search(r"\bport\s*(\d{1,5})\b", low)
    if m:
        return "TCP", int(m.group(1))
    for name in sorted(SERVICES, key=len, reverse=True):
        if re.search(rf"\b{name}\b", low):
            return SERVICES[name]
    m = re.search(r"\b(tcp|udp)\b", low)
    return (m.group(1).upper(), None) if m else None


def _one_based(n: int, what: str) -> int:
    if n < 1:
        raise LexError(f"{what} count from 1 (the first is {what[:-1]} 1)")
    return n - 1


def position_in(text: str) -> Optional[int]:
    """Where to insert an ACL rule, as the engine's 0-based position, or None to append at the end.
    People count from 1: "at position 1", "as rule 1", "at the top" and "first" all mean 0."""
    low = text.lower()
    m = re.search(r"\b(?:at position|in position|as rule|at rule|position)\s*#?(\d+)\b", low)
    if m:
        return _one_based(int(m.group(1)), "positions")
    if re.search(r"\b(at the top|at the start|at the beginning|first)\b", low):
        return 0
    return None


def rule_number_in(text: str) -> Optional[int]:
    """"rule 2" / "rule #2" / "the second rule" -> 0-based index 1."""
    low = text.lower()
    m = re.search(r"\brule\s*#?(\d+)\b", low)
    if m:
        return _one_based(int(m.group(1)), "rules")
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    m = re.search(r"\bthe (first|second|third|fourth|fifth) rule\b", low)
    return ordinals[m.group(1)] - 1 if m else None


def number_after(text: str, words: str) -> Optional[int]:
    """The first standalone number after one of ``words`` (regex alternation), skipping digits that
    are part of names or addresses: "metric of R1's route to 50" -> 50."""
    low = text.lower()
    key = re.search(rf"\b(?:{words})\b", low)
    if not key:
        return None
    m = re.search(r"(?<![\w.])(\d+)(?![\w.])", low[key.end():])
    return int(m.group(1)) if m else None


class Lexicon:
    """Device names for one network: ids, labels, addresses, and unambiguous role words."""

    def __init__(self, net: Network):
        self.net = net
        self.names = node_lookup(net)
        for word, typ in _ROLE_TYPES.items():
            of_type = [n.id for n in net.nodes if n.type == typ]
            if len(of_type) == 1:  # "the firewall" only means something when there is one
                self.names.setdefault(word, of_type[0])
                self.names.setdefault(f"the {word}", of_type[0])
        self.by_ip = {ip: n.id for n in net.nodes for ip in n.ip_addresses}

    def device(self, word: str) -> Optional[str]:
        """The device a single name or address refers to, or None."""
        w = word.strip()
        return self.names.get(w.lower()) or self.by_ip.get(w)

    def devices_in(self, text: str) -> list[str]:
        """Devices mentioned in ``text`` by name or address, in order of appearance, each once.
        An address followed by a prefix length or mask is a destination, not a device."""
        found = [(m.start(), nid) for name, nid in self.names.items()
                 for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I)]
        found += [(m.start(), self.by_ip[m.group(1)])
                  for m in re.finditer(rf"(?<![\d.])({IP})(?![\d.])(?!\s*/)(?!\s+255\.)", text)
                  if m.group(1) in self.by_ip]
        out: list[str] = []
        for _, nid in sorted(found):
            if nid not in out:
                out.append(nid)
        return out

    def unknown_names(self, text: str) -> list[tuple[str, Optional[str]]]:
        """Words shaped like device names (R22, FWW, USR) that name no device, each with the closest
        real device as a suggestion when there is a close one."""
        out: list[tuple[str, Optional[str]]] = []
        for m in _NAME_SHAPED.finditer(text):
            word = m.group(1)
            if word.upper() in _STOP or self.device(word):
                continue
            close = difflib.get_close_matches(word.lower(), list(self.names), n=1, cutoff=0.6)
            out.append((word, self.names[close[0]] if close else None))
        return out

    def route_covering(self, router: str, device: str) -> Optional[str]:
        """The prefix of ``router``'s most specific static route that contains ``device``'s address."""
        node = next((n for n in self.net.nodes if n.id == device), None)
        if node is None or not node.ip:
            return None
        ip = ipaddress.ip_address(node.ip)
        best = None
        for r in self.net.routes:
            if r.router == router and ip in (p := ipaddress.ip_network(r.destination)):
                if best is None or p.prefixlen > best.prefixlen:
                    best = p
        return str(best) if best else None
