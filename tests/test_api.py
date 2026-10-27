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
    assert "enterprise" in {n["id"] for n in d["networks"]}


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


def test_eval_run_is_bounded_and_returns_harness_result():
    r = client.post("/api/eval/run", json={"sites": [2], "commands": 5, "seed": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["commands"] == 5 and body["runs"][0]["sites"] == 2
    assert set(body["runs"][0]["arms"]) == {"none", "lint", "reachability", "full", "incremental"}
    assert client.post("/api/eval/run", json={"sites": [64]}).status_code == 422
    assert client.post("/api/eval/run", json={"commands": 5000}).status_code == 422


def _wait(job_id, timeout=120):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/eval/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} still running after {timeout}s")


def test_eval_job_runs_in_the_background_and_reports_progress():
    r = client.post("/api/eval/jobs", json={"sites": [1], "commands": 5, "seeds": [1, 2]})
    assert r.status_code == 202
    start = r.json()
    assert start["status"] == "running" and start["total"] == 1 * 2 * 5 * 5  # sizes x seeds x arms x commands
    job = _wait(start["id"])
    assert job["status"] == "done" and job["done"] == job["total"]
    assert job["result"]["config"]["seeds"] == [1, 2] and job["result"]["runs"][0]["sites"] == 1


def test_one_eval_job_at_a_time_and_cancelling_it():
    slow = client.post("/api/eval/jobs", json={"sites": [12], "commands": 100, "seeds": [1, 2, 3, 4, 5]}).json()
    try:
        busy = client.post("/api/eval/jobs", json={"sites": [1], "commands": 5})
        assert busy.status_code == 409 and "already running" in busy.json()["detail"]
    finally:
        assert client.post(f"/api/eval/jobs/{slow['id']}/cancel").status_code == 200
    job = _wait(slow["id"])
    assert job["status"] == "cancelled" and job["done"] < job["total"] and "result" not in job


def test_eval_job_errors():
    assert client.get("/api/eval/jobs/nope").status_code == 404
    assert client.post("/api/eval/jobs/nope/cancel").status_code == 404
    assert client.post("/api/eval/jobs", json={"sites": [13]}).status_code == 422  # 12 sites (76 devices) is the cap
    assert client.post("/api/eval/jobs", json={"sites": [1], "seeds": [1, 2, 3, 4, 5, 6]}).status_code == 422
