"""Incremental verification: re-simulate only the traffic a change can affect.

Why this is sound.  ``simulate`` decides what happens at each device from that device's own
routes, ACL and links.  A change touches a known set of devices (``Effect.nodes``): the router
whose route was edited, the device whose ACL was edited, or the two ends of a link.  Every other
device forwards exactly as before.  So a traffic class whose current path never visits a touched
device takes the same path afterwards, and its cached trace is still correct.  For a route change
the class must also be headed for an address inside the changed prefix, because a route that does
not match the destination never takes part in the lookup.

``IncrementalVerifier`` keeps the live model's traces and an index from device to the classes that
cross it.  It is a drop-in ``Verifier`` for the gatekeeper and returns the same report as
``analyze``.  The counterfactual and its forwarding state are also built from the live ones by
replacing only what the change touches, so they share objects with the live model.  The live
model must therefore not be edited in place; the gatekeeper never does.
"""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .changes import Effect, apply_changes
from .impact import AnalysisOptions, ChangeReport, assess
from .models import Change, Network
from .network import NetworkState, Trace, simulate
from .verify import TrafficClass, build_classes


@dataclass
class _Base:
    """Everything derived from the live model."""
    net: Network
    key: tuple  # the options that decide which classes exist
    state: NetworkState
    classes: dict[str, TrafficClass]
    traces: dict[str, Trace]
    by_node: dict[str, set[str]]  # device -> classes whose trace visits it
    ips: dict[str, Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]]


@dataclass
class _Candidate:
    """The outcome of the last verification, kept in case that command is executed."""
    net: Network
    key: tuple
    state: NetworkState
    changes: list[Change]
    traces: dict[str, Trace]
    affected: set[str]


def _widens_classes(changes: list[Change]) -> bool:
    """Could the change add traffic classes to those of the current model?"""
    return any(c.operation == "ADD_POLICY" or (c.operation == "ADD_ACL_RULE" and c.rule.port is not None)
               for c in changes)


def _alters_classes(changes: list[Change]) -> bool:
    """Could the model that results from the change have a different set of classes?"""
    return _widens_classes(changes) or any(c.operation in ("DELETE_POLICY", "DELETE_ACL_RULE") for c in changes)


def _index(traces: dict[str, Trace]) -> dict[str, set[str]]:
    by_node: dict[str, set[str]] = defaultdict(set)
    for k, t in traces.items():
        for n in t.path:
            by_node[n].add(k)
    return by_node


def _sim(state: NetworkState, c: TrafficClass) -> Trace:
    return simulate(state, c.source, c.destination, c.protocol, c.port)


class IncrementalVerifier:
    def __init__(self) -> None:
        self._base: Optional[_Base] = None
        self._last: Optional[_Candidate] = None
        self.builds = 0  # times the cache was computed from scratch
        self.advances = 0  # times it was carried forward after an executed command

    def __call__(self, network: Network, changes: list[Change], options: AnalysisOptions) -> ChangeReport:
        t0 = time.perf_counter()
        base = self._sync(network, options)
        cf_net, inverses, effects = apply_changes(network, changes, share=True)
        after = base.state.derive(cf_net, {n for e in effects for n in e.nodes})

        affected = self._affected(base, effects)
        if _widens_classes(changes):
            classes = build_classes([network, cf_net], probes=options.probes, probe_limit=options.probe_limit)
            tb = {k: base.traces[k] if k in base.traces else _sim(base.state, c) for k, c in classes.items()}
            affected = (affected & classes.keys()) | (classes.keys() - base.traces.keys())
        else:
            classes, tb = base.classes, base.traces
        ta = dict(tb)
        for k in affected:
            ta[k] = _sim(after, classes[k])

        report = assess(network, cf_net, changes, inverses, effects, base.state, after, classes, tb, ta,
                        options, t0, self)
        report.meta["resimulated"] = len(affected)
        # set last: the rollback check inside assess calls this verifier again, for a different command
        self._last = _Candidate(cf_net, base.key, after, changes, ta, affected)
        return report

    # ------------------------------------------------------------------ the cache
    def _sync(self, network: Network, options: AnalysisOptions) -> _Base:
        """Return the cache for ``network``, carrying it forward if the last command was executed."""
        key = (options.probes, options.probe_limit)
        base, last = self._base, self._last
        if base is not None and base.net is network and base.key == key:
            return base
        if base is not None and last is not None and last.key == key and network == last.net:
            self._base = self._advance(base, last, network)
            self.advances += 1
        else:
            self._base = self._build(network, key)
            self.builds += 1
        self._last = None
        return self._base

    def _build(self, network: Network, key: tuple) -> _Base:
        state = NetworkState(network)
        classes = build_classes([network], probes=key[0], probe_limit=key[1])
        traces = {k: _sim(state, c) for k, c in classes.items()}
        ips = {n.id: ipaddress.ip_address(n.ip) if n.ip else None for n in network.nodes}
        return _Base(network, key, state, classes, traces, _index(traces), ips)

    def _advance(self, base: _Base, last: _Candidate, network: Network) -> _Base:
        if _alters_classes(last.changes):
            classes = build_classes([network], probes=last.key[0], probe_limit=last.key[1])
            traces = {k: last.traces[k] if k in last.traces else _sim(last.state, c) for k, c in classes.items()}
            return _Base(network, last.key, last.state, classes, traces, _index(traces), base.ips)
        for k in last.affected:
            for n in base.traces[k].path:
                base.by_node[n].discard(k)
            for n in last.traces[k].path:
                base.by_node[n].add(k)
        return _Base(network, last.key, last.state, base.classes, last.traces, base.by_node, base.ips)

    def _affected(self, base: _Base, effects: list[Effect]) -> set[str]:
        keys: set[str] = set()
        for e in effects:
            if e.kind == "route":
                prefix = ipaddress.ip_network(e.prefix)
                for k in base.by_node.get(e.nodes[0], ()):
                    ip = base.ips.get(base.classes[k].destination)
                    if ip is None or ip in prefix:
                        keys.add(k)
            elif e.kind in ("link", "acl"):
                for n in e.nodes:
                    keys |= base.by_node.get(n, set())
        return keys
