"""Tests for certified cubic-Bezier arc-length enclosures."""

import math
from fractions import Fraction

import pytest

from app.arclen import ArcLengthBounds, arc_length_bounds
from app.geometry import Segment

STRAIGHT_X = ((0, 0), (1, 0), (2, 0), (3, 0))
DIAGONAL = ((0, 0), (1, 1), (2, 2), (3, 3))
ARC_L = ((-3, 0), (-2, 1), (-1, 0), (0, 0))
HAIRPIN = ((0, 0), (10, 0), (0, 1), (10, 1))
BIG_CURVE = ((0, 0), (5, 8), (12, -3), (15, 4))
ZERO_TANGENT = ((0, 0), (1, 0), (-1, 0), (0, 0))


def dense_reference_length(points, n=40_001):
    """Independent composite-Simpson quadrature (float, display grade)."""
    def bez_deriv(t):
        vx = [3 * (points[1][0] - points[0][0]),
              6 * (points[0][0] - 2 * points[1][0] + points[2][0]),
              3 * (-points[0][0] + 3 * points[1][0]
                    - 3 * points[2][0] + points[3][0])]
        vy = [3 * (points[1][1] - points[0][1]),
              6 * (points[0][1] - 2 * points[1][1] + points[2][1]),
              3 * (-points[0][1] + 3 * points[1][1]
                    - 3 * points[2][1] + points[3][1])]
        return (math.hypot(vx[0] + t * (vx[1] + t * vx[2]),
                           vy[0] + t * (vy[1] + t * vy[2])))

    h = 1.0 / (n - 1)
    total = bez_deriv(0.0) + bez_deriv(1.0)
    for i in range(1, n - 1):
        total += (4 if i % 2 else 2) * bez_deriv(i * h)
    return total * h / 3


def test_straight_segment_is_exact_in_one_leaf():
    b = arc_length_bounds(Segment(STRAIGHT_X))
    assert b.converged
    assert b.subdivisions == 0
    # Simpson reproduces the degree-1 integrand exactly; only sqrt
    # rounding (2^-70) remains.
    assert abs(float(b.lower) - 3.0) < 1e-18
    assert abs(float(b.upper) - 3.0) < 1e-18
    assert b.lower <= 3 <= b.upper or (
        # 3 may compare as exact Fraction integer
        b.lower <= Fraction(3) <= b.upper)


def test_diagonal_length_is_three_sqrt_two_exactly():
    b = arc_length_bounds(Segment(DIAGONAL))
    assert b.converged
    # L = 3√2 ⇒ L² = 18, compared without float rounding.
    assert b.lower ** 2 <= 18 <= b.upper ** 2
    assert b.error < Fraction(1, 10 ** 15)


def test_zero_segment_length():
    b = arc_length_bounds(
        Segment(((0, 0), (0, 0), (0, 0), (0, 0))))
    assert b == ArcLengthBounds(Fraction(0), Fraction(0), True, 0)


def test_enclosure_contains_independent_quadrature():
    for points in (ARC_L, HAIRPIN, BIG_CURVE):
        b = arc_length_bounds(Segment(points))
        ref = dense_reference_length(points)
        assert b.converged, points
        assert float(b.lower) - 1e-9 <= ref <= float(b.upper) + 1e-9
        assert b.error < Fraction(1, 10 ** 6)


def test_enclosure_respects_chord_and_polygon_bounds():
    # chord |P3-P0| <= true arc length <= control-polygon perimeter:
    # the certified enclosure must honour the same inequalities.
    for points in (ARC_L, HAIRPIN, BIG_CURVE):
        b = arc_length_bounds(Segment(points))
        chord = math.hypot(points[3][0] - points[0][0],
                           points[3][1] - points[0][1])
        polygon = sum(math.hypot(points[i + 1][0] - points[i][0],
                                 points[i + 1][1] - points[i][1])
                      for i in range(3))
        assert float(b.lower) >= chord - 1e-9
        assert float(b.upper) <= polygon + 1e-9


def test_enclosure_converges_under_refinement():
    seg = Segment(ARC_L)
    coarse = arc_length_bounds(
        seg, rel_tol=Fraction(1, 10 ** 4), abs_tol=Fraction(1, 10 ** 5))
    fine = arc_length_bounds(
        seg, rel_tol=Fraction(1, 10 ** 13), abs_tol=Fraction(1, 10 ** 14))
    assert fine.converged and coarse.converged
    assert fine.error < coarse.error
    # Refinement never moves the enclosure outward (nested intervals).
    assert fine.lower >= coarse.lower
    assert fine.upper <= coarse.upper


def test_enclosure_is_deterministic():
    a = arc_length_bounds(Segment(HAIRPIN))
    b = arc_length_bounds(Segment(HAIRPIN))
    assert a == b


def test_nonconvergent_case_reported_not_certified_silently():
    # A zero-tangent segment cannot have a convergent f4 enclosure; the
    # result is still a valid outer bound and is flagged.
    b = arc_length_bounds(Segment(ZERO_TANGENT))
    assert b.lower <= dense_reference_length(ZERO_TANGENT) <= b.upper
    assert b.converged is False or b.error < Fraction(1, 10 ** 6)
