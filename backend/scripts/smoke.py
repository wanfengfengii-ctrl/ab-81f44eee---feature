#!/usr/bin/env python3
"""Business smoke test for the audit API.

Runs inside the one-shot ``verify`` compose service.  Exercises the audit
endpoint with representative business payloads (pass, curvature exceeded,
zero tangent, junction break, invalid input) and exits non-zero on the
first unexpected result.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB_URL = os.environ.get("WEB_URL", "http://web:80").rstrip("/")

ARC_L = {"points": [[-3, 0], [-2, 1], [-1, 0], [0, 0]]}
ARC_R = {"points": [[0, 0], [1, 0], [2, 1], [3, 0]]}
PIN_L = {"points": [[0, 0], [10, 0], [0, 1], [10, 1]]}
PIN_R = {"points": [[10, 1], [20, 1], [10, 2], [20, 2]]}
CUSP = {"points": [[0, 0], [1, 0], [-1, 0], [0, 0]]}


def call(path: str, payload=None):
    url = f"{API_URL}{path}"
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def get(url: str) -> int:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status


def expect(cond: bool, label: str, detail="") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        raise SystemExit(1)


def main() -> None:
    print(f"target API: {API_URL}")
    print(f"target WEB: {WEB_URL}")

    status, body = call("/health")
    expect(status == 200 and body.get("status") == "ok",
          "API health endpoint", str(body))

    expect(get(f"{WEB_URL}/index.html") == 200,
          "WEB serves the audit page (via web container)")

    # 1. valid G2 spline passes and reports per-segment maxima
    status, body = call("/api/audit",
                        {"segments": [ARC_L, ARC_R], "max_curvature": 2.0})
    expect(status == 200, "pass-case HTTP 200", str(status))
    expect(body.get("ok") is True, "pass-case ok=true", str(body)[:300])
    segs = body.get("segments", [])
    expect(len(segs) == 2 and all(s["max_curvature"] > 0 for s in segs),
           "pass-case reports 2 segment maxima with locations", str(segs))

    # 2. interior extremum that endpoint checks alone would miss
    status, body = call("/api/audit",
                        {"segments": [PIN_L, PIN_R], "max_curvature": 1.0})
    err = body.get("error") or {}
    expect(body.get("ok") is False, "hairpin ok=false")
    expect(err.get("code") == "CURVATURE_EXCEEDED",
           "hairpin code=CURVATURE_EXCEEDED", str(err))
    expect(err.get("segment") == 0, "hairpin earliest segment=0", str(err))
    expect(0 < err.get("parameter", -1) < 1,
           "hairpin parameter inside segment", str(err))
    expect(isinstance(err.get("point"), list) and len(err["point"]) == 2,
           "hairpin reports coordinates", str(err))
    expect(err.get("curvature", 0) > 1.0,
           "hairpin reports over-limit curvature", str(err))

    # stability: same draft twice -> identical answer
    _, body2 = call("/api/audit",
                    {"segments": [PIN_L, PIN_R], "max_curvature": 1.0})
    expect(body == body2, "audit result is stable for repeated drafts")

    # 3. zero tangent vector -> non-runnable
    status, body = call("/api/audit",
                        {"segments": [CUSP, ARC_R], "max_curvature": 100.0})
    err = (body.get("error") or {})
    expect(err.get("code") == "ZERO_TANGENT",
           "zero-tangent code=ZERO_TANGENT", str(err))

    # 4. junction break
    broken = {"points": [[1, 0], [2, 0], [3, 0], [4, 0]]}
    status, body = call("/api/audit",
                        {"segments": [ARC_L, broken], "max_curvature": 100.0})
    expect((body.get("error") or {}).get("code") == "POSITION_DISCONTINUITY",
           "position discontinuity detected", str(body.get("error")))

    # 5. structural validation
    status, body = call("/api/audit",
                        {"segments": [ARC_L], "max_curvature": 1.0})
    expect(status == 422 and
           body.get("error", {}).get("code") == "INVALID_INPUT",
           "single segment rejected with 422", str(body))

    # 6. anti-corrosion travel review ------------------------------------
    # 6a. absent block keeps the historical response shape
    status, body = call("/api/audit",
                        {"segments": [ARC_L, ARC_R], "max_curvature": 2.0})
    expect("coating_review" not in body,
           "review absent when feature not enabled", str(body)[:200])

    review_block = {
        "enabled": True, "segment_times": [1, 1],
        "min_speed": 1.0, "max_speed": 5.0,
    }
    status, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": review_block})
    cr = body.get("coating_review") or {}
    expect(status == 200 and cr.get("certified") is True,
           "review certifies an in-band plan", str(cr)[:300])
    segs = cr.get("segments", [])
    expect(len(segs) == 2 and cr.get("total_time") == 2,
           "review reports per-segment records and total time", str(cr)[:300])
    for i, s in enumerate(segs):
        al = s.get("arc_length", {})
        sp = s.get("speed", {})
        expect(isinstance(al.get("lower"), (int, float)) and
               0 < al["lower"] <= al.get("upper", 0.0) and
               al.get("error", 1.0) >= 0 and
               sp.get("lower", 0.0) >= 1.0 and
               sp.get("upper", 9.0) <= 5.0,
               f"segment {i} shows convergent arc-length/speed enclosures",
               str(s)[:200])
    # true arc length of the arc must beat its chord (3) and stay under
    # its control-polygon perimeter (~6.4)
    l0 = segs[0]["arc_length"]
    expect(3.0 < l0["lower"] and l0["upper"] < 6.5,
           "certified arc length respects chord/polygon bounds", str(l0))

    # 6b. too fast (whole derived interval above the band)
    _, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {**review_block,
                           "min_speed": 0.1, "max_speed": 1.0}})
    err = (body.get("coating_review") or {}).get("error") or {}
    expect(err.get("code") == "TOO_FAST" and err.get("segment") == 0 and
           err.get("speed_lower", 0.0) > err.get("max_speed", 0.0),
           "too-fast plan names the first segment with speed evidence",
           str(err))

    # 6c. too slow
    _, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {"enabled": True, "segment_times": [100, 100],
                           "min_speed": 1.0, "max_speed": 5.0}})
    err = (body.get("coating_review") or {}).get("error") or {}
    expect(err.get("code") == "TOO_SLOW" and
           err.get("speed_upper", 9.0) < err.get("min_speed", 0.0),
           "too-slow plan rejected with speed evidence", str(err))

    # 6d. straddling a limit -> insufficient margin
    _, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {**review_block, "min_speed": 1e-9,
                           "max_speed": 3.1834899612}})
    err = (body.get("coating_review") or {}).get("error") or {}
    expect(err.get("code") == "INSUFFICIENT_MARGIN",
           "limit-straddling interval demands safety margin", str(err))

    # 6e. earliest segment reported in travel order (seg 1 slow, seg 0 ok)
    _, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {"enabled": True, "segment_times": [1, 1000],
                           "min_speed": 1.0, "max_speed": 5.0}})
    err = (body.get("coating_review") or {}).get("error") or {}
    expect(err.get("code") == "TOO_SLOW" and err.get("segment") == 1,
           "first uncertifiable segment reported in segment order", str(err))

    # 6f. invalid review block -> 422
    status, body = call("/api/audit", {
        "segments": [ARC_L, ARC_R], "max_curvature": 2.0,
        "coating_review": {"enabled": True, "segment_times": [1.5, 1],
                           "min_speed": 1.0, "max_speed": 5.0}})
    expect(status == 422 and
           body.get("error", {}).get("code") == "INVALID_INPUT",
           "non-integer spraying time rejected with 422", str(body))

    # 6g. review is never attached to a failed audit
    status, body = call("/api/audit", {
        "segments": [PIN_L, PIN_R], "max_curvature": 1.0,
        "coating_review": review_block})
    expect(body.get("ok") is False and "coating_review" not in body,
           "failed audit carries no review", str(body)[:200])

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.exit(0)
