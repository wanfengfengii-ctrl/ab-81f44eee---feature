"""Tests for the certified cubic-Bezier arc-length enclosure."""

from fractions import Fraction

import pytest

from app.arclength import (
    ABS_TOL,
    ArcLengthBounds,
    arc_length_bounds,
    split_midpoint,
    sqrt_bounds,
)

STRAIGHT = ((0, 0), (1, 0), (2, 0), (3, 0))
ARC = ((-3, 0), (-2, 1), (-1, 0), (0, 0))
# Self-retracing curve with two interior zero-speed points.
LOOP = ((0, 0), (1, 0), (-1, 0), (0, 0))


def test_sqrt_bounds_bracket_the_root():
    for x in (Fraction(0), Fraction(2), Fraction(1, 10 ** 9),
              Fraction(123456789, 987654321)):
        lo, hi = sqrt_bounds(x)
        assert lo * lo <= x <= hi * hi
        assert hi - lo <= Fraction(1, 10 ** 15)


def test_straight_segment_has_exact_length():
    b = arc_length_bounds(STRAIGHT)
    assert b.lower == 3 and b.upper == 3 and b.error == 0


def test_enclosure_is_valid_and_convergent():
    b = arc_length_bounds(ARC)
    assert isinstance(b, ArcLengthBounds)
    assert 0 < b.lower <= b.upper
    assert b.error <= ABS_TOL + Fraction(1, 10 ** 12) * b.lower
    # Independent high-order Gauss-Legendre value for this arc.
    assert abs(float(b.lower) - 3.183489961117) < 1e-9
    assert abs(float(b.upper) - 3.183489961117) < 1e-9


def test_midpoint_split_preserves_geometric_bounds():
    pts = tuple((Fraction(p[0]), Fraction(p[1])) for p in ARC)
    left, right = split_midpoint(pts)
    # The two child curves share the split point.
    assert left[3] == right[0]
    b_all = arc_length_bounds(ARC)
    b_l = arc_length_bounds(left)
    b_r = arc_length_bounds(right)
    assert b_l.lower + b_r.lower >= b_all.lower - Fraction(1, 10 ** 11)
    assert b_l.upper + b_r.upper <= b_all.upper + Fraction(1, 10 ** 11)


def test_loop_with_cusps_has_positive_length():
    # The curve retraces itself; its length exceeds the zero chord even
    # though both endpoints coincide.
    b = arc_length_bounds(LOOP)
    assert b.lower > 0
    # Integral of 3|6t^2 - 6t + 1| over [0,1] equals 2/sqrt(3).
    assert b.lower <= 2 / (3 ** 0.5) <= b.upper


def test_tighter_tolerance_shrinks_the_enclosure():
    coarse = arc_length_bounds(
        ARC, rel_tol=Fraction(1, 10 ** 4), abs_tol=Fraction(1, 10 ** 4))
    fine = arc_length_bounds(ARC)
    assert coarse.error > fine.error
    # The fine enclosure lies inside the coarse enclosure.
    assert coarse.lower <= fine.lower and fine.upper <= coarse.upper


def test_uniform_scaling_scales_the_length():
    pts = [(x * 7, y * 7) for x, y in ARC]
    b = arc_length_bounds(pts)
    base = arc_length_bounds(ARC)
    assert float(b.lower / 7) == pytest.approx(float(base.lower), abs=1e-11)
    assert float(b.upper / 7) == pytest.approx(float(base.upper), abs=1e-11)


def test_degenerate_point_segment_is_zero():
    b = arc_length_bounds(((4, 4), (4, 4), (4, 4), (4, 4)))
    assert b.lower == 0 and b.upper == 0
