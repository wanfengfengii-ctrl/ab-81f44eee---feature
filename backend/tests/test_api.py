"""HTTP-level tests using FastAPI's in-process test client."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ARC_L = {"points": [[-3, 0], [-2, 1], [-1, 0], [0, 0]]}
ARC_R = {"points": [[0, 0], [1, 0], [2, 1], [3, 0]]}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_audit_pass_payload():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["segments"]) == 2
    assert body["segments"][0]["max_curvature"] > 0


def test_audit_fail_payload():
    pin_l = {"points": [[0, 0], [10, 0], [0, 1], [10, 1]]}
    pin_r = {"points": [[10, 1], [20, 1], [10, 2], [20, 2]]}
    r = client.post("/api/audit", json={
        "segments": [pin_l, pin_r], "max_curvature": 1.0})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "CURVATURE_EXCEEDED"
    assert body["error"]["segment"] == 0
    assert "curvature" in body["error"] and "point" in body["error"]


def test_audit_invalid_payload():
    r = client.post("/api/audit", json={"segments": [ARC_L],
                                        "max_curvature": 1.0})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_coating_disabled_is_absent():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0})
    assert r.status_code == 200
    assert "coating" not in r.json()


def test_coating_certified_response():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating": {"enabled": True, "spray_durations": [1, 1],
                    "min_speed": 3.0, "max_speed": 3.5}})
    assert r.status_code == 200
    c = r.json()["coating"]
    assert c["certified"] is True
    assert c["total_duration"] == 2
    assert all("arc_length" in s and "speed" in s for s in c["segments"])


def test_coating_too_fast_response():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating": {"enabled": True, "spray_durations": [1, 1],
                    "min_speed": 1.0, "max_speed": 2.0}})
    c = r.json()["coating"]
    assert c["certified"] is False
    assert c["error"]["code"] == "SPEED_TOO_FAST"
    assert c["error"]["segment"] == 0


def test_coating_invalid_payload_is_422():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating": {"enabled": True, "spray_durations": [-1, 1],
                    "min_speed": 1.0, "max_speed": 2.0}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_coating_on_failed_audit_not_evaluated():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 0.1,
        "coating": {"enabled": True, "spray_durations": [1, 1],
                    "min_speed": 1.0, "max_speed": 9.0}})
    body = r.json()
    assert body["ok"] is False and "coating" not in body
