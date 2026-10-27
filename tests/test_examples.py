"""The built-in example networks (netguardx/examples/*.json) load and start out clean."""
import ipaddress
import json
from pathlib import Path

import pytest

from netguardx import Network
from netguardx.verify import verify_network

EX = Path(__file__).parent.parent / "netguardx" / "examples"
NETWORKS = sorted(p.stem for p in EX.glob("*.json"))


def load(name: str) -> Network:
    return Network.model_validate(json.loads((EX / f"{name}.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", NETWORKS)
def test_baseline_is_clean(name):
    s = verify_network(load(name)).summary
    assert s["policies_violated"] == 0 and s["static_issues"] == 0, s


@pytest.mark.parametrize("name", NETWORKS)
def test_addresses_are_unique_and_every_device_is_placed(name):
    net = load(name)
    ips = [ipaddress.ip_address(a) for n in net.nodes for a in n.ip_addresses]
    assert len(ips) == len(set(ips))
    assert all(n.x is not None and n.y is not None for n in net.nodes)


def test_enterprise_is_review_sized_and_every_flow_is_delivered():
    net = load("enterprise")
    assert 50 <= len(net.nodes) <= 75
    base = verify_network(net)
    declared = {f.key for f in net.flows}
    assert [t.key for t in base.traces if t.key in declared and not t.delivered] == []


def test_enterprise_has_the_zones_the_scenarios_use():
    ids = {n.id for n in load("enterprise").nodes}
    for zone in ("INET", "FW-EDGE", "DMZ-R", "CORE1", "CORE2", "DC-FW", "DB-FW", "SAN-R", "DB1",
                 "MGMT-R", "JUMP", "WAN-R", "BR1-R", "GUEST-R", "DEV-R"):
        assert zone in ids
