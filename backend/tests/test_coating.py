"""Tests for the anti-corrosion travel review certification."""

import math

import pytest

from app.audit import audit
from app.coating import CoatingInputError, parse_review

ARC_L = {"points": [[-3, 0], [-2, 1], [-1, 0], [0, 0]]}
ARC_R = {"points": [[0, 0], [1, 0], [2, 1], [3, 0]]}
BASE = {"segments": [ARC_L, ARC_R], "max_curvature": 2.0}

ARC_LENGTH = 3.183489961057  # certified enclosure centre, both segments


def review_payload(times, vmin=1.0, vmax=5.0, **extra):
    block = {"enabled": True, "segment_times": list(times),
             "min_speed": vmin, "max_speed": vmax}
    block.update(extra)
    payload = dict(BASE)
    payload["coating_review"] = block
    return payload


def run(times, vmin=1.0, vmax=5.0):
    return audit(review_payload(times, vmin, vmax))["coating_review"]


# --------------------------------------------------------------------------
# Backwards compatibility
# --------------------------------------------------------------------------

def test_payload_without_review_keeps_historical_shape():
    r = audit(BASE)
    assert r["ok"] is True
    assert "coating_review" not in r
    assert set(r) == {"ok", "max_curvature", "error", "segments"}


def test_disabled_review_leaves_response_untouched():
    payload = dict(BASE)
    payload["coating_review"] = {"enabled": False}
    assert "coating_review" not in audit(payload)
    payload["coating_review"] = {}
    assert "coating_review" not in audit(payload)


def test_review_absent_on_failed_audit():
    payload = review_payload([1, 1])
    payload["max_curvature"] = 0.01
    r = audit(payload)
    assert r["ok"] is False
    assert "coating_review" not in r


# --------------------------------------------------------------------------
# Certification decisions
# --------------------------------------------------------------------------

def test_whole_speed_interval_inside_closed_band_certifies():
    cr = run([1, 1], 1.0, 5.0)
    assert cr["certified"] is True and cr["error"] is None
    assert cr["total_time"] == 2
    for seg in cr["segments"]:
        assert seg["status"] == "certified"
        assert seg["arc_length"]["converged"] is True
        assert seg["speed"]["lower"] >= 1.0
        assert seg["speed"]["upper"] <= 5.0
        # Bounds are ordered and tight.
        assert 0 <= seg["arc_length"]["error"] < 1e-6


def test_interval_wholly_above_band_is_too_fast():
    cr = run([1, 1], 0.1, 1.0)
    assert cr["certified"] is False
    err = cr["error"]
    assert err["code"] == "TOO_FAST"
    assert err["segment"] == 0
    assert err["speed_lower"] > err["max_speed"]


def test_interval_wholly_below_band_is_too_slow():
    cr = run([100, 100], 1.0, 5.0)
    assert cr["certified"] is False
    err = cr["error"]
    assert err["code"] == "TOO_SLOW"
    assert err["segment"] == 0
    assert err["speed_upper"] < err["min_speed"]


def test_interval_straddling_limit_is_insufficient_margin():
    # Limit cuts through the derived interval.
    cr0 = run([1, 1], 1e-9, 1e9)
    s0 = cr0["segments"][0]["speed"]
    mid = (s0["lower"] + s0["upper"]) / 2

    over = run([1, 1], 1e-9, mid)
    assert over["error"]["code"] == "INSUFFICIENT_MARGIN"
    assert over["error"]["boundary"] == "max"

    under = run([1, 1], mid, 1e9)
    assert under["error"]["code"] == "INSUFFICIENT_MARGIN"
    assert under["error"]["boundary"] == "min"

    both = run([1, 1], s0["lower"] + 0.3 * (s0["upper"] - s0["lower"]),
               s0["upper"] - 0.3 * (s0["upper"] - s0["lower"]))
    assert both["error"]["code"] == "INSUFFICIENT_MARGIN"
    assert both["error"]["boundary"] == "both"


def test_closed_interval_endpoint_is_certified():
    # A closed band that contains the entire (tight) enclosure
    # certifies; the limits sit on the derived interval, exercising the
    # non-strict comparison rather than a comfortable margin.
    cr0 = run([1, 1], 1e-9, 1e9)
    s0 = cr0["segments"][0]["speed"]
    cr = run([1, 1], s0["lower"] * (1 - 1e-9),
             s0["upper"] * (1 + 1e-9))
    assert cr["certified"] is True
    # ... while a band cut just inside the enclosure does not.
    cr2 = run([1, 1], s0["lower"] + 0.25 * s0["error"],
              s0["upper"] - 0.25 * s0["error"])
    assert cr2["certified"] is False
    assert cr2["error"]["code"] == "INSUFFICIENT_MARGIN"


def test_first_uncertifiable_segment_is_reported_in_order():
    # Segment 0 fine, segment 1 far too slow: segment 1 is named.
    cr = run([1, 1000], 1.0, 5.0)
    assert cr["error"]["code"] == "TOO_SLOW"
    assert cr["error"]["segment"] == 1
    # Segment 0's record is still displayed.
    assert cr["segments"][0]["status"] == "certified"


def test_reported_speed_evidence_matches_record():
    cr = run([1, 1], 0.1, 1.0)
    err, rec = cr["error"], cr["segments"][0]
    assert err["speed_lower"] == rec["speed"]["lower"]
    assert err["speed_upper"] == rec["speed"]["upper"]
    assert err["arc_length_lower"] == rec["arc_length"]["lower"]
    assert err["arc_length_upper"] == rec["arc_length"]["upper"]


def test_result_is_stable_for_repeated_drafts():
    a = audit(review_payload([1, 1]))
    b = audit(review_payload([1, 1]))
    assert a == b


# --------------------------------------------------------------------------
# Structural validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("block", [
    {"enabled": True, "segment_times": [1],
     "min_speed": 1.0, "max_speed": 5.0},                       # count
    {"enabled": True, "segment_times": [0, 1],
     "min_speed": 1.0, "max_speed": 5.0},                       # non-positive
    {"enabled": True, "segment_times": [-2, 1],
     "min_speed": 1.0, "max_speed": 5.0},
    {"enabled": True, "segment_times": [1.5, 1],
     "min_speed": 1.0, "max_speed": 5.0},                       # non-integer
    {"enabled": True, "segment_times": [True, 1],
     "min_speed": 1.0, "max_speed": 5.0},                       # bool
    {"enabled": True, "segment_times": "1,1",
     "min_speed": 1.0, "max_speed": 5.0},
    {"enabled": True, "segment_times": [1, 1],
     "min_speed": 0.0, "max_speed": 5.0},                       # zero speed
    {"enabled": True, "segment_times": [1, 1],
     "min_speed": -1.0, "max_speed": 5.0},
    {"enabled": True, "segment_times": [1, 1],
     "min_speed": 5.0, "max_speed": 1.0},                       # reversed
    {"enabled": True, "segment_times": [1, 1],
     "min_speed": 1.0, "max_speed": float("inf")},
    "not-a-dict",
])
def test_invalid_review_blocks(block):
    payload = dict(BASE)
    payload["coating_review"] = block
    with pytest.raises(CoatingInputError):
        audit(payload)


def test_parse_review_absent_and_disabled():
    assert parse_review({}) is None
    assert parse_review({"coating_review": None}) is None
    assert parse_review({"coating_review": {"enabled": False}}) is None
    cfg = parse_review({"coating_review": {
        "enabled": True, "segment_times": [2, 3],
        "min_speed": 1.5, "max_speed": 4}})
    assert cfg is not None
    assert [int(t) for t in cfg["times"]] == [2, 3]


def test_total_spray_time_is_sum_of_integer_times():
    cr = run([3, 7], 0.001, 100.0)
    assert cr["total_time"] == 10
