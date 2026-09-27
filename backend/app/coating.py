"""Anti-corrosion travel review ("防腐走行复核").

Enabled by the equipment engineer only *after* the curvature audit has
passed for the current draft.  For every segment the engineer fills a
positive-integer spraying time; a single pair of minimum/maximum
allowed travel speeds applies to the whole spline.

Certification is a certified-interval decision, never a point estimate:

* the segment's **continuous true arc length** is enclosed rigorously by
  :mod:`app.arclen` as ``L ∈ [L_lo, L_hi]`` (rational endpoints,
  convergent error bound — no control polygon, no screen pixels, no
  fixed-parameter sampling);
* with the given integer time ``T`` the real average travel speed
  ``L/T`` therefore lies in ``[L_lo/T, L_hi/T]``;
* the segment is certified only when this **whole** speed interval is
  inside the closed allowed band ``[v_min, v_max]``;
* an interval wholly above the band is TOO_FAST, wholly below is
  TOO_SLOW, and an interval straddling either limit is
  INSUFFICIENT_MARGIN (the plan needs more safety margin).

Segments are scanned in travel order, so the first uncertifiable
segment is reported deterministically.  Any later edit to a control
point or a travel parameter invalidates the conclusion client-side; the
server is stateless and recomputes from the submitted draft.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from .arclen import ArcLengthBounds, arc_length_bounds
from .geometry import Segment


class CoatingInputError(ValueError):
    """Raised when the coating review block is structurally invalid."""


def _positive_decimal(value: Any, label: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoatingInputError(f"{label}必须为正数")
    fv = float(value)
    if not (fv > 0.0) or fv != fv or fv == float("inf"):
        raise CoatingInputError(f"{label}必须为有限正数")
    # Fraction(str(float)) keeps the exact decimal the engineer typed.
    return Fraction(str(fv))


def parse_review(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract and validate the optional coating_review request block.

    Returns None when the feature is not enabled for the draft (absent
    or explicitly disabled), so historical payloads and responses keep
    their original shape.
    """
    raw = payload.get("coating_review")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CoatingInputError("防腐走行复核参数格式无效")
    if not raw.get("enabled", False):
        return None

    times_raw = raw.get("segment_times")
    if not isinstance(times_raw, list) or not times_raw:
        raise CoatingInputError("必须为每一段填写喷涂时长")
    times: List[Fraction] = []
    for i, t in enumerate(times_raw):
        if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
            raise CoatingInputError(
                f"第 {i + 1} 段喷涂时长必须为正整数（时间单位）")
        times.append(Fraction(t))

    vmin = _positive_decimal(raw.get("min_speed"), "最小允许喷涂速度")
    vmax = _positive_decimal(raw.get("max_speed"), "最大允许喷涂速度")
    if vmin > vmax:
        raise CoatingInputError("最小允许喷涂速度不得大于最大允许喷涂速度")

    return {"times": times, "min_speed": vmin, "max_speed": vmax}


def _fraction_float(x: Fraction) -> float:
    return float(x)


def _segment_record(index: int, time_s: Fraction,
                    bounds: ArcLengthBounds, vmin: Fraction,
                    vmax: Fraction) -> Tuple[Dict[str, Any],
                                             Optional[Dict[str, Any]]]:
    """Build one segment record and its failure (if any), travel order."""
    speed_lo = bounds.lower / time_s
    speed_hi = bounds.upper / time_s

    # Certified only if the *entire* derived interval is in [vmin, vmax].
    if speed_hi <= vmax and speed_lo >= vmin:
        status, problem = "certified", None
    elif speed_lo > vmax:
        status, problem = "too_fast", "TOO_FAST"
    elif speed_hi < vmin:
        status, problem = "too_slow", "TOO_SLOW"
    else:
        status, problem = "insufficient_margin", "INSUFFICIENT_MARGIN"

    # Integer-time window [L_hi/v_max, L_lo/v_min] inside which the whole
    # derived speed interval would be contained; empty when the current
    # arc-length uncertainty alone already straddles the band.
    window_lo = bounds.upper / vmax
    window_hi = bounds.lower / vmin
    feasible = window_lo <= window_hi

    record: Dict[str, Any] = {
        "index": index,
        "time": time_s.numerator // time_s.denominator,
        "status": status,
        "arc_length": {
            "lower": _fraction_float(bounds.lower),
            "upper": _fraction_float(bounds.upper),
            "error": _fraction_float(bounds.error),
            "converged": bounds.converged,
            "subdivisions": bounds.subdivisions,
        },
        "speed": {
            "lower": _fraction_float(speed_lo),
            "upper": _fraction_float(speed_hi),
            "error": _fraction_float(speed_hi - speed_lo),
        },
        "time_window": {
            "lower": _fraction_float(window_lo),
            "upper": _fraction_float(window_hi),
            "feasible": feasible,
        },
    }

    failure: Optional[Dict[str, Any]] = None
    if problem is not None:
        boundary = None
        if problem == "INSUFFICIENT_MARGIN":
            over_hi = speed_hi > vmax
            under_lo = speed_lo < vmin
            boundary = "both" if over_hi and under_lo else (
                "max" if over_hi else "min")
        failure = {
            "code": problem,
            "segment": index,
            "boundary": boundary,
            "time": record["time"],
            "arc_length_lower": record["arc_length"]["lower"],
            "arc_length_upper": record["arc_length"]["upper"],
            "speed_lower": record["speed"]["lower"],
            "speed_upper": record["speed"]["upper"],
            "min_speed": _fraction_float(vmin),
            "max_speed": _fraction_float(vmax),
            "time_window_lower": record["time_window"]["lower"],
            "time_window_upper": record["time_window"]["upper"],
            "time_window_feasible": feasible,
        }
    return record, failure


def review_segments(segments: List[Segment],
                    config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the review over an audit-passing spline."""
    times = config["times"]
    vmin = config["min_speed"]
    vmax = config["max_speed"]
    if len(times) != len(segments):
        raise CoatingInputError(
            "喷涂时长段数必须与曲线段数一致")

    records: List[Dict[str, Any]] = []
    first_failure: Optional[Dict[str, Any]] = None
    certified = True
    for i, (seg, time_s) in enumerate(zip(segments, times)):
        bounds = arc_length_bounds(seg)
        record, failure = _segment_record(i, time_s, bounds, vmin, vmax)
        records.append(record)
        # An audit-passing spline has Q(t) > 0 everywhere, so the
        # enclosure always converges; guard anyway (never certify on a
        # non-convergent enclosure).
        if not bounds.converged and first_failure is None:
            first_failure = {
                "code": "NOT_CONVERGED",
                "segment": i,
                "boundary": None,
                "time": record["time"],
                "arc_length_lower": record["arc_length"]["lower"],
                "arc_length_upper": record["arc_length"]["upper"],
                "speed_lower": record["speed"]["lower"],
                "speed_upper": record["speed"]["upper"],
                "min_speed": _fraction_float(vmin),
                "max_speed": _fraction_float(vmax),
                "time_window_lower": None,
                "time_window_upper": None,
                "time_window_feasible": False,
            }
            record["status"] = "not_converged"
            certified = False
        elif failure is not None and first_failure is None:
            first_failure = failure
            certified = False

    total_time = sum(t.numerator for t in times)
    message = None
    if first_failure is not None:
        idx = first_failure["segment"] + 1
        if first_failure["code"] == "NOT_CONVERGED":
            message = (
                f"第 {idx} 段弧长包围未能在预算内收敛，"
                f"无法给出可认证的速度区间，须增加安全余量")
        elif first_failure["code"] == "TOO_FAST":
            message = (
                f"第 {idx} 段走行过快：速度区间 "
                f"[{first_failure['speed_lower']:.6g}, "
                f"{first_failure['speed_upper']:.6g}] 整体高于最大允许速度 "
                f"{first_failure['max_speed']:.6g}")
        elif first_failure["code"] == "TOO_SLOW":
            message = (
                f"第 {idx} 段走行过慢：速度区间 "
                f"[{first_failure['speed_lower']:.6g}, "
                f"{first_failure['speed_upper']:.6g}] 整体低于最小允许速度 "
                f"{first_failure['min_speed']:.6g}")
        else:
            message = (
                f"第 {idx} 段安全余量不足：速度区间 "
                f"[{first_failure['speed_lower']:.6g}, "
                f"{first_failure['speed_upper']:.6g}] 跨越允许速度闭区间 "
                f"[{first_failure['min_speed']:.6g}, "
                f"{first_failure['max_speed']:.6g}]，须增加安全余量")
        first_failure["message"] = message

    return {
        "enabled": True,
        "certified": certified,
        "min_speed": _fraction_float(vmin),
        "max_speed": _fraction_float(vmax),
        "total_time": total_time,
        "segments": records,
        "error": first_failure,
    }
