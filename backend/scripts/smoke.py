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

    # 6. coating travel review ------------------------------------------------
    coat_base = {"segments": [ARC_L, ARC_R], "max_curvature": 2.0}

    # 6a. disabled: response shape stays exactly the historical audit shape
    status, body = call("/api/audit", coat_base)
    expect("coating" not in body, "coating absent when not enabled")

    # 6b. certified plan: per-segment durations, arc-length enclosures,
    # speed ranges and total duration are all present.
    status, body = call("/api/audit", {**coat_base, "coating": {
        "enabled": True, "spray_durations": [1, 1],
        "min_speed": 3.0, "max_speed": 3.5}})
    c = body.get("coating") or {}
    expect(c.get("certified") is True, "coating certified inside band", str(c))
    rows = c.get("segments", [])
    expect(len(rows) == 2 and c.get("total_duration") == 2,
           "coating reports 2 rows and total duration", str(c))
    for s in rows:
        L = s.get("arc_length", {})
        v = s.get("speed", {})
        expect(isinstance(L.get("lower"), (int, float)) and
               L["lower"] > 0 and L["upper"] >= L["lower"] and
               L.get("error", -1) >= 0 and
               v.get("lower", 0) > 0 and v["upper"] >= v["lower"],
               f"segment {s.get('index')} has arc bounds + speed range",
               str(s))
        # The speed range must come from true arc length / duration.
        expect(abs(v["lower"] - L["lower"] / s["duration"]) < 1e-9 and
               abs(v["upper"] - L["upper"] / s["duration"]) < 1e-9,
               f"segment {s.get('index')} speed = arc length / duration",
               str(s))

    # 6c. whole interval outside the band -> explicit first bad segment
    status, body = call("/api/audit", {**coat_base, "coating": {
        "enabled": True, "spray_durations": [1, 1],
        "min_speed": 1.0, "max_speed": 2.0}})
    err = (body.get("coating") or {}).get("error") or {}
    expect(err.get("code") == "SPEED_TOO_FAST" and err.get("segment") == 0,
           "over-speed plan reports SPEED_TOO_FAST on segment 0", str(err))
    expect(err.get("speed_lower", 0) > 2.0 and
           err.get("arc_length_upper", 0) >= err.get("arc_length_lower", 0),
           "over-speed error carries speed + arc-length evidence", str(err))

    # 6d. interval straddles the limit -> safety margin required
    status, body = call("/api/audit", {**coat_base, "coating": {
        "enabled": True, "spray_durations": [1, 1],
        "min_speed": 3.183489961116, "max_speed": 9.0}})
    err = (body.get("coating") or {}).get("error") or {}
    expect(err.get("code") == "MARGIN_INSUFFICIENT",
           "limit-straddling plan requires more margin", str(err))

    # 6e. later segment is the first bad one -> stable travel-order report
    straight0 = {"points": [[0, 0], [1, 0], [2, 0], [3, 0]]}
    straight1 = {"points": [[3, 0], [4, 0], [5, 0], [6, 0]]}
    status, body = call("/api/audit", {
        "segments": [straight0, straight1], "max_curvature": 10.0,
        "coating": {"enabled": True, "spray_durations": [1, 100],
                    "min_speed": 1.0, "max_speed": 10.0}})
    err = (body.get("coating") or {}).get("error") or {}
    expect(err.get("segment") == 1 and err.get("code") == "SPEED_TOO_SLOW",
           "under-speed points at segment 1 in travel order", str(err))

    # 6f. invalid coating parameters share the 422 contract
    status, body = call("/api/audit", {**coat_base, "coating": {
        "enabled": True, "spray_durations": [1.5, 1],
        "min_speed": 1.0, "max_speed": 2.0}})
    expect(status == 422 and
           body.get("error", {}).get("code") == "INVALID_INPUT",
           "non-integer duration rejected with 422", str(body))

    # 6g. coating cannot run on a draft that fails the curvature audit
    status, body = call("/api/audit", {
        "segments": [PIN_L, PIN_R], "max_curvature": 1.0,
        "coating": {"enabled": True, "spray_durations": [1, 1],
                    "min_speed": 1.0, "max_speed": 9.0}})
    expect(body.get("ok") is False and "coating" not in body,
           "coating withheld until curvature audit passes", str(body)[:300])

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
    sys.exit(0)
