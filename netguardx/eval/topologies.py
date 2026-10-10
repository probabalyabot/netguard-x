"""Generated networks of a chosen size.

``campus_network(sites)`` repeats the pattern of the built-in three-tier example: every site has a
user, an app server and a database behind a firewall, plus a side router that physically connects
to the database without crossing the firewall.  Sites hang off a ring of core routers, and the
internet attaches to the first core.  The structure is fully determined by its parameters.
"""
from __future__ import annotations

from typing import Optional

import networkx as nx

from ..models import Network
from ..verify import verify_network

MAX_SITES = 250  # site i owns 10.i.0.0/16; 10.254/16 and 10.255/16 are infrastructure


def campus_network(sites: int, cores: Optional[int] = None) -> Network:
    if not 1 <= sites <= MAX_SITES:
        raise ValueError(f"sites must be between 1 and {MAX_SITES}")
    k = max(1, sites // 4) if cores is None else cores
    if not 1 <= k <= 250:
        raise ValueError("cores must be between 1 and 250")

    nodes: list[dict] = [{"id": "INET", "type": "internet", "ip_addresses": ["203.0.113.1"], "label": "Internet"}]
    links: list[dict] = [{"source": "INET", "destination": "C0"}]
    routes: list[dict] = [{"router": "INET", "destination": "0.0.0.0/0", "next_hop": "C0"}]
    acls: list[dict] = []
    flows: list[dict] = []
    policies: list[dict] = []

    ring = nx.Graph()
    ring.add_nodes_from(range(k))
    if k == 2:
        ring.add_edge(0, 1)
    elif k > 2:
        ring.add_edges_from((j, (j + 1) % k) for j in range(k))
    # every node gets map coordinates, so the UI draws sites as rows instead of a computed layout
    nodes[0].update(x=0.02, y=0.02)
    for j in range(k):
        nodes.append({"id": f"C{j}", "type": "router", "ip_addresses": [f"10.254.0.{j + 1}"],
                      "x": 0.1, "y": round((j + 0.5) / k, 4)})
    links += [{"source": f"C{a}", "destination": f"C{b}"} for a, b in ring.edges()]

    def toward(j: int, target: int) -> str:
        return f"C{nx.shortest_path(ring, j, target)[1]}"

    for j in range(k):
        routes.append({"router": f"C{j}", "destination": "0.0.0.0/0", "next_hop": "INET" if j == 0 else toward(j, 0)})

    for i in range(sites):
        home = i % k
        user, app, db, r, fw, m = f"USER{i}", f"APP{i}", f"DB{i}", f"R{i}", f"FW{i}", f"M{i}"
        y, dy = (i + 0.5) / sites, 0.3 / sites
        up, mid, down = round(y - dy, 4), round(y, 4), round(y + dy, 4)
        nodes += [
            {"id": user, "type": "host", "ip_addresses": [f"10.{i}.0.10"], "x": 0.45, "y": up},
            {"id": app, "type": "server", "ip_addresses": [f"10.{i}.2.10"], "criticality": 3, "x": 0.45, "y": down},
            {"id": db, "type": "server", "ip_addresses": [f"10.{i}.5.10"], "criticality": 5, "x": 0.9, "y": mid},
            {"id": r, "type": "router", "ip_addresses": [f"10.255.{i}.1"], "x": 0.3, "y": mid},
            {"id": m, "type": "router", "ip_addresses": [f"10.255.{i}.2"], "x": 0.68, "y": down},
            {"id": fw, "type": "firewall", "ip_addresses": [f"10.255.{i}.10"], "x": 0.68, "y": up},
        ]
        links += [
            {"source": user, "destination": r}, {"source": app, "destination": r},
            {"source": r, "destination": f"C{home}"}, {"source": r, "destination": fw},
            {"source": fw, "destination": db},
            {"source": r, "destination": m}, {"source": m, "destination": db, "cost": 20},
        ]
        routes += [
            {"router": user, "destination": "0.0.0.0/0", "next_hop": r},
            {"router": app, "destination": "0.0.0.0/0", "next_hop": r},
            {"router": db, "destination": "0.0.0.0/0", "next_hop": fw},
            {"router": r, "destination": f"10.{i}.5.0/24", "next_hop": fw},
            {"router": r, "destination": "0.0.0.0/0", "next_hop": f"C{home}"},
            {"router": fw, "destination": "0.0.0.0/0", "next_hop": r},
            {"router": m, "destination": "0.0.0.0/0", "next_hop": r},
        ]
        for j in range(k):
            routes.append({"router": f"C{j}", "destination": f"10.{i}.0.0/16",
                           "next_hop": r if j == home else toward(j, home)})
        acls.append({"node": fw, "source": app, "destination": db, "protocol": "TCP", "port": 5432, "action": "ALLOW"})
        flows += [
            {"source": user, "destination": app, "protocol": "TCP", "port": 443, "criticality": 2},
            {"source": app, "destination": db, "protocol": "TCP", "port": 5432, "criticality": 5},
            {"source": app, "destination": "INET", "protocol": "TCP", "port": 443},
        ]
        if sites > 1:
            flows.append({"source": user, "destination": f"APP{(i + 1) % sites}", "protocol": "TCP", "port": 443,
                          "criticality": 2})
        policies += [
            {"action": "ALLOW", "source": app, "destination": db, "protocol": "TCP", "port": 5432, "waypoint": fw},
            {"action": "DENY", "source": user, "destination": db, "protocol": "TCP", "port": 5432},
            {"action": "DENY", "source": "INET", "destination": db, "protocol": "TCP", "port": 5432},
            {"action": "ALLOW", "source": user, "destination": app, "protocol": "TCP", "port": 443},
        ]

    net = Network.model_validate({"name": f"Campus network ({sites} sites, {k} cores)", "nodes": nodes,
                                  "links": links, "routes": routes, "acls": acls, "flows": flows,
                                  "policies": policies})
    base = verify_network(net)
    undelivered = {t.key for t in base.traces if not t.delivered} & {f.key for f in net.flows}
    if base.summary["policies_violated"] or base.summary["static_issues"] or undelivered:
        raise RuntimeError(f"generated network is not clean: {base.summary}, undelivered flows {sorted(undelivered)}")
    return net
