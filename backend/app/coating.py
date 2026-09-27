"""防腐走行复核 (coating-travel review).

Enabled by the equipment engineer only after the curvature audit has
passed for the current draft.  Every segment gets a positive-integer
spray duration, and the draft gets one unified closed speed band
``[min_speed, max_speed]``.

The actual travel speed is derived from the segment's *true continuous
arc length* (see :mod:`app.arclength`) and the typed duration:

    v(t) over the segment = L / d,    L in [L_lo, L_hi]

so the whole certified speed interval of the segment is
``[L_lo/d, L_hi/d]``.  Certification rules use that entire interval:

* contained in the closed band           -> certified;
* strictly above ``max_speed``            -> SPEED_TOO_FAST;
* strictly below ``min_speed``            -> SPEED_TOO_SLOW;
* crossing either limit                   -> MARGIN_INSUFFICIENT
  (the engineer must add safety margin).

The first failing segment in travel order is reported deterministically.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, List

from .arclength import arc_length_bounds
from .geometry import Segment


class CoatingInputError(ValueError):
    """Raised when the coating section of the request is invalid."""


def _fraction_speed(value: Any, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoatingInputError(f"{name}必须为有限正数")
    fv = float(value)
    if not (fv > 0.0) or fv != fv or fv == float("inf"):
        raise CoatingInputError(f"{name}必须为有限正数")
    # Capture the exact decimal the engineer typed.
    return Fraction(str(fv))


def parse_coating(payload: Dict[str, Any], n_segments: int
                  ) -> Dict[str, Any]:
    """Validate the coating block; returns normalized parameters."""
    raw_durations = payload.get("spray_durations")
    if not isinstance(raw_durations, list) or len(raw_durations) != n_segments:
        raise CoatingInputError(
            f"喷涂时长必须为长度 {n_segments}（每段一个）的数组")
    durations: List[int] = []
    for i, d in enumerate(raw_durations):
        if isinstance(d, bool) or not isinstance(d, int) or d <= 0:
            raise CoatingInputError(
                f"第 {i + 1} 段喷涂时长必须为正整数")
        durations.append(int(d))

    vmin = _fraction_speed(payload.get("min_speed"), "最小允许喷涂速度")
    vmax = _fraction_speed(payload.get("max_speed"), "最大允许喷涂速度")
    if vmin > vmax:
        raise CoatingInputError("最小允许喷涂速度不得大于最大允许喷涂速度")
    return {"durations": durations, "min_speed": vmin, "max_speed": vmax}


def _flo(x: Fraction) -> float:
    return float(x)


def coating_review(segments: List[Segment], params: Dict[str, Any]
                   ) -> Dict[str, Any]:
    """Build the coating verdict from certified arc-length enclosures."""
    durations = params["durations"]
    vmin = params["min_speed"]
    vmax = params["max_speed"]

    segment_rows: List[Dict[str, Any]] = []
    certified = True
    first_error: Dict[str, Any] | None = None

    for i, seg in enumerate(segments):
        d = durations[i]
        length = arc_length_bounds(seg.points)
        speed_lo = length.lower / d
        speed_hi = length.upper / d
        row = {
            "index": i,
            "duration": d,
            "arc_length": {
                "lower": _flo(length.lower),
                "upper": _flo(length.upper),
                "error": _flo(length.error),
            },
            "speed": {"lower": _flo(speed_lo), "upper": _flo(speed_hi)},
            "certified": False,
        }

        problem: Dict[str, Any] | None = None
        if speed_lo > vmax:
            problem = {
                "code": "SPEED_TOO_FAST",
                "message": (
                    f"第 {i + 1} 段速度区间 "
                    f"[{_flo(speed_lo):.6g}, {_flo(speed_hi):.6g}] "
                    f"整体高于最大允许速度 {_flo(vmax):.6g}"),
                "kind": "too_fast",
            }
        elif speed_hi < vmin:
            problem = {
                "code": "SPEED_TOO_SLOW",
                "message": (
                    f"第 {i + 1} 段速度区间 "
                    f"[{_flo(speed_lo):.6g}, {_flo(speed_hi):.6g}] "
                    f"整体低于最小允许速度 {_flo(vmin):.6g}"),
                "kind": "too_slow",
            }
        elif speed_lo < vmin or speed_hi > vmax:
            # The derived interval straddles at least one closed-band
            # boundary: points of the travel may lie outside the band.
            problem = {
                "code": "MARGIN_INSUFFICIENT",
                "message": (
                    f"第 {i + 1} 段速度区间 "
                    f"[{_flo(speed_lo):.6g}, {_flo(speed_hi):.6g}] "
                    f"跨越允许速度闭区间 [{_flo(vmin):.6g}, "
                    f"{_flo(vmax):.6g}]，须增加安全余量"),
                "kind": "margin_insufficient",
            }

        if problem is None:
            row["certified"] = True
        else:
            certified = False
            problem.update({
                "segment": i,
                "speed_lower": _flo(speed_lo),
                "speed_upper": _flo(speed_hi),
                "arc_length_lower": _flo(length.lower),
                "arc_length_upper": _flo(length.upper),
                "arc_length_error": _flo(length.error),
                "duration": d,
                "min_speed": _flo(vmin),
                "max_speed": _flo(vmax),
                "point": None,
                "parameter": None,
            })
            if first_error is None:
                first_error = problem

        segment_rows.append(row)

    return {
        "enabled": True,
        "min_speed": _flo(vmin),
        "max_speed": _flo(vmax),
        "certified": certified,
        "total_duration": sum(durations),
        "segments": segment_rows,
        "error": first_error,
    }
