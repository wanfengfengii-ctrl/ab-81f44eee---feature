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


def test_audit_without_review_has_no_review_key():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0})
    assert "coating_review" not in r.json()


def test_coating_review_certified_via_http():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {
            "enabled": True, "segment_times": [1, 1],
            "min_speed": 1.0, "max_speed": 5.0}})
    assert r.status_code == 200
    cr = r.json()["coating_review"]
    assert cr["certified"] is True
    assert cr["total_time"] == 2
    for seg in cr["segments"]:
        assert seg["arc_length"]["lower"] <= seg["arc_length"]["upper"]
        assert seg["speed"]["lower"] >= 1.0
        assert seg["speed"]["upper"] <= 5.0


def test_coating_review_too_fast_via_http():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {
            "enabled": True, "segment_times": [1, 1],
            "min_speed": 0.1, "max_speed": 1.0}})
    cr = r.json()["coating_review"]
    assert cr["certified"] is False
    assert cr["error"]["code"] == "TOO_FAST"
    assert cr["error"]["segment"] == 0


def test_coating_review_invalid_block_is_422():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {
            "enabled": True, "segment_times": [1.5, 1],
            "min_speed": 1.0, "max_speed": 5.0}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_coating_review_requires_passing_audit():
    r = client.post("/api/audit", json={
        "segments": [ARC_L, ARC_R], "max_curvature": 0.01,
        "coating_review": {
            "enabled": True, "segment_times": [1, 1],
            "min_speed": 1.0, "max_speed": 5.0}})
    body = r.json()
    assert body["ok"] is False
    assert "coating_review" not in body
