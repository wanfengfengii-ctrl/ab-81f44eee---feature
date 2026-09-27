"""End-to-end tests for the coating-travel review."""

import math

import pytest

from app.audit import audit
from app.coating import CoatingInputError, coating_review, parse_coating
from app.geometry import Segment

ARC_L = [[-3, 0], [-2, 1], [-1, 0], [0, 0]]
ARC_R = [[0, 0], [1, 0], [2, 1], [3, 0]]
PASS_PAYLOAD = {"segments": [{"points": ARC_L}, {"points": ARC_R}],
                "max_curvature": 2.0}

# Straight tangent-compatible pieces: exact length 3 per segment.
S0 = {"points": [[0, 0], [1, 0], [2, 0], [3, 0]]}
S1 = {"points": [[3, 0], [4, 0], [5, 0], [6, 0]]}
STRAIGHT = {"segments": [S0, S1], "max_curvature": 10.0}


def coating(enabled=True, durations=(1, 1), vmin=1.0, vmax=9.0):
    return {"enabled": enabled, "spray_durations": list(durations),
            "min_speed": vmin, "max_speed": vmax}


def test_disabled_review_leaves_response_unchanged():
    r = audit(PASS_PAYLOAD)
    assert "coating" not in r


def test_enabled_returns_arc_length_enclosure_and_speed_range():
    r = audit({**PASS_PAYLOAD, "coating": coating()})
    c = r["coating"]
    assert c["enabled"] is True and c["total_duration"] == 2
    for row in c["segments"]:
        L = row["arc_length"]
        assert 0 < L["lower"] <= L["upper"]
        assert L["error"] >= 0
        assert row["speed"]["lower"] == pytest.approx(L["lower"], rel=1e-12)
        assert row["speed"]["upper"] == pytest.approx(L["upper"], rel=1e-12)


def test_certified_whole_interval_inside_closed_band():
    r = audit({**PASS_PAYLOAD, "coating": coating(vmin=3.0, vmax=3.5)})
    assert r["coating"]["certified"] is True
    assert r["coating"]["error"] is None
    assert all(s["certified"] for s in r["coating"]["segments"])


def test_entire_interval_above_limit_is_too_fast():
    # arc length ~3.183, duration 1 -> speed ~3.183; band well below.
    r = audit({**PASS_PAYLOAD, "coating": coating(vmin=1.0, vmax=2.0)})
    c = r["coating"]
    assert c["certified"] is False
    assert c["error"]["code"] == "SPEED_TOO_FAST"
    assert c["error"]["segment"] == 0
    assert c["error"]["speed_lower"] > 2.0


def test_entire_interval_below_limit_is_too_slow():
    r = audit({**PASS_PAYLOAD, "coating": coating(vmin=5.0, vmax=6.0)})
    c = r["coating"]
    assert c["certified"] is False
    assert c["error"]["code"] == "SPEED_TOO_SLOW"
    assert c["error"]["segment"] == 0
    assert c["error"]["speed_upper"] < 5.0


def test_crossing_limit_requires_margin():
    # min speed inside the certified interval -> straddling.
    r = audit({**PASS_PAYLOAD,
               "coating": coating(vmin=3.183489961116, vmax=9.0)})
    c = r["coating"]
    assert c["certified"] is False
    assert c["error"]["code"] == "MARGIN_INSUFFICIENT"
    assert c["error"]["segment"] == 0


def test_touching_closed_boundary_is_certified():
    # Exact rational speed 3; band touching it on both sides.
    r = audit({**STRAIGHT,
               "coating": coating(vmin=3.0, vmax=3.0)})
    assert r["coating"]["certified"] is True


def test_first_failing_segment_in_travel_order():
    r = audit({**STRAIGHT,
               "coating": coating(durations=(1, 100), vmin=1.0, vmax=10.0)})
    e = r["coating"]["error"]
    assert e["segment"] == 1 and e["code"] == "SPEED_TOO_SLOW"


def test_per_segment_flags_independent_of_first_error():
    r = audit({**STRAIGHT,
               "coating": coating(durations=(1, 100), vmin=1.0, vmax=10.0)})
    rows = r["coating"]["segments"]
    assert rows[0]["certified"] is True
    assert rows[1]["certified"] is False


def test_review_not_evaluated_when_audit_fails():
    bad = audit({"segments": [{"points": ARC_L},
                              {"points": [[1, 0], [2, 0], [3, 0], [4, 0]]}],
                 "max_curvature": 2.0, "coating": coating()})
    assert bad["ok"] is False
    assert "coating" not in bad


@pytest.mark.parametrize("block,match", [
    ({"enabled": True, "spray_durations": [1], "min_speed": 1.0,
      "max_speed": 2.0}, "数组"),
    ({"enabled": True, "spray_durations": [1.5, 1], "min_speed": 1.0,
      "max_speed": 2.0}, "正整数"),
    ({"enabled": True, "spray_durations": [0, 1], "min_speed": 1.0,
      "max_speed": 2.0}, "正整数"),
    ({"enabled": True, "spray_durations": [1, 1], "min_speed": 0.0,
      "max_speed": 2.0}, "正数"),
    ({"enabled": True, "spray_durations": [1, 1], "min_speed": 3.0,
      "max_speed": 2.0}, "不得大于"),
])
def test_invalid_coating_inputs(block, match):
    with pytest.raises(CoatingInputError, match=match):
        parse_coating(block, 2)


def test_result_is_deterministic():
    p = {**PASS_PAYLOAD, "coating": coating(vmin=3.0, vmax=3.5)}
    assert audit(p) == audit(p)


def test_unit_helper_shape():
    seg = Segment(((0, 0), (1, 0), (2, 0), (3, 0)))
    params = parse_coating(coating(durations=(1,), vmin=1.0, vmax=9.0), 1)
    out = coating_review([seg], params)
    assert out["segments"][0]["duration"] == 1
    assert math.isclose(out["segments"][0]["arc_length"]["lower"], 3.0)
