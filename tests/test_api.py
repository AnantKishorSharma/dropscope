from fastapi.testclient import TestClient

from dropscope.api import create_app


def _post(client, src, dst, qp, reason="BUFFER_FULL", queue=3, ts=100.0):
    return client.post("/api/ingest", json={
        "ts": ts, "ingress_port": "Ethernet0", "src_ip": src, "dst_ip": dst,
        "qp_num": qp, "queue": queue, "drop_reason": reason,
    })


def test_ingest_and_summary(registry):
    client = TestClient(create_app(registry))
    r = _post(client, "10.0.1.5", "10.0.1.6", 1500)
    assert r.status_code == 200
    assert r.json()["job_id"] == "job-a"

    _post(client, "10.0.2.5", "10.0.2.6", 2500, ts=101.0)

    summary = client.get("/api/summary").json()
    assert summary["total_drops"] == 2
    job_ids = {row["job_id"] for row in summary["top_jobs"]}
    assert {"job-a", "job-b"} <= job_ids


def test_jobs_and_flows_endpoints(registry):
    client = TestClient(create_app(registry))
    _post(client, "10.0.1.5", "10.0.1.6", 1500)
    _post(client, "10.0.1.5", "10.0.1.6", 1500, ts=101.0)

    jobs = client.get("/api/jobs").json()["jobs"]
    a = next(j for j in jobs if j["job_id"] == "job-a")
    assert a["drops"] == 2
    assert a["name"] == "A"

    flows = client.get("/api/jobs/job-a/flows").json()["flows"]
    assert len(flows) == 1
    assert flows[0]["drops"] == 2


def test_unattributed_ingest(registry):
    client = TestClient(create_app(registry))
    r = _post(client, "10.8.8.8", "10.8.8.9", None)
    assert r.json()["job_id"] is None


def test_ingest_rejects_invalid_payload(registry):
    client = TestClient(create_app(registry))
    r = client.post("/api/ingest", json={
        "ts": 1.0, "ingress_port": "e", "src_ip": "10.0.1.5",
        "dst_ip": "10.0.1.6", "count": 0,  # count must be >= 1
    })
    assert r.status_code == 422


def test_websocket_snapshot(registry):
    client = TestClient(create_app(registry))
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "total_drops" in msg["data"]
