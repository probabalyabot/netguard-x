import json

from fastapi.testclient import TestClient

from netguardx.api import app
from conftest import EX

client = TestClient(app)
NET = json.loads((EX / "basic.json").read_text())


def test_health_and_index():
    assert client.get("/api/health").json()["status"] == "ok"
    assert "NetGuard-X" in client.get("/").text


def test_examples():
    d = client.get("/api/examples").json()
    assert d["networks"][0]["id"] == "basic" and len(d["changes"]) >= 5


def test_verify():
    r = client.post("/api/verify", json={"network": NET})
    assert r.status_code == 200 and r.json()["summary"]["policies_violated"] == 0


def test_simulate_returns_report_and_markdown():
    ch = json.loads((EX / "changes" / "route-via-r3.json").read_text())["changes"]
    r = client.post("/api/simulate", json={"network": NET, "changes": ch})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["decision"] == "NOT_RECOMMENDED"
    assert body["report_markdown"].startswith("# Network change verification")
    assert body["topology"]["nodes"] and body["impact_graph"]["edges"]


def test_simulate_custom_weights():
    ch = json.loads((EX / "changes" / "route-loop.json").read_text())["changes"]
    r = client.post("/api/simulate", json={"network": NET, "changes": ch,
                                           "weights": {"broken_flows": 0, "routing_failures": 0, "criticality": 0}})
    assert r.json()["risk"]["score"] == 0


def test_errors_are_readable():
    r = client.post("/api/simulate", json={"network": NET, "changes": [
        {"operation": "DELETE_ROUTE", "router": "R1", "destination": "192.0.2.0/24"}]})
    assert r.status_code == 422 and "no route" in r.json()["detail"]
    r = client.post("/api/simulate", json={"network": NET, "changes": [{"operation": "ADD_LINK", "node_a": "R1"}]})
    assert r.status_code == 422 and "node_b" in r.json()["detail"]
    r = client.post("/api/verify", json={"network": {"nodes": [{"id": "A"}, {"id": "A"}]}})
    assert r.status_code == 422 and "duplicate" in r.json()["detail"]


def test_interpret():
    r = client.post("/api/interpret", json={"text": "remove the link between R2 and FW", "network": NET})
    assert r.json()["changes"][0]["operation"] == "DELETE_LINK"


def test_diff():
    ch = json.loads((EX / "changes" / "backup-link.json").read_text())["changes"]
    d = client.post("/api/diff", json={"network": NET, "changes": ch}).json()
    assert d["flow_deltas"][0]["outcome"] == "path_changed"


def test_map_is_laid_out_for_networks_without_coordinates(net):
    from netguardx import analyze
    from conftest import load_change

    bare = json.loads(net.model_dump_json(exclude={"nodes": {"__all__": {"x", "y"}}}))
    ch = json.loads((EX / "changes" / "route-via-r3.json").read_text())["changes"]
    for path, body in [("/api/verify", {"network": bare}), ("/api/simulate", {"network": bare, "changes": ch}),
                       ("/api/diff", {"network": bare, "changes": ch})]:
        r = client.post(path, json=body)
        assert r.status_code == 200
        assert all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in r.json()["topology"]["nodes"])
    # the engine itself leaves the map alone
    report = analyze(type(net).model_validate(bare), load_change("route-via-r3"))
    assert all(n["x"] is None for n in report.topology["nodes"])


def test_verify_returns_topology(net):
    r = client.post("/api/verify", json={"network": net.model_dump()})
    assert r.status_code == 200
    assert r.json()["topology"]["nodes"]
