"""Certified arc length of a cubic Bezier segment.

The coating review must derive the travel speed from the segment's *true
continuous arc length* -- never from the control polygon, a screen drawing
or a fixed-parameter sample.  The exact arc length of a cubic Bezier is an
elliptic integral with no closed form, so this module returns a rigorous
enclosure [lower, upper] of the true length with a certified error.

Two independent families of bounds are used:

* **Geometric outer bounds.**  The chord ``|B(b)-B(a)|`` is a lower bound
  (the straight line is shortest), while the length of the control polygon
  ``|P1-P0| + |P2-P1| + |P3-P2|`` is an upper bound (de Casteljau
  subdivision polygons have monotonically non-increasing lengths
  converging to the curve).  The control polygon therefore only *bounds*
  the answer; it is never taken as the answer.  These bounds are the
  fallback on leaves that may contain a zero-speed point.
* **Simpson enclosure of the speed integral.**  The arc length is
  ``integral_0^1 sqrt(S(t)) dt`` with ``S(t) = |B'(t)|^2`` a quartic with
  exact (here integer) coefficients.  On a leaf of width h the one-panel
  Simpson rule has the rigorous remainder
  ``|integral f - h/6 (f(a) + 4 f(m) + f(b))| <= h^5/2880 max |f''''|``;
  the derivatives of ``f = sqrt(S)`` up to order four are bounded over the
  leaf from the exact finite Taylor expansion of S.  This converges as
  O(h^5), so a few thousand leaves reach a 1e-12 relative enclosure.

Leaves whose certified speed lower bound reaches zero (a possible cusp
inside) are subdivided further and use the geometric bounds; such leaves
shrink geometrically.  Every square root is an integer
:func:`math.isqrt` floor/ceil enclosure.  To keep exact rational
summation cheap, each leaf interval is additionally rounded outward onto
a fixed global grid (density 1e-17); over a few thousand leaves this
widens the total enclosure by at most ~1e-13, far inside the requested
tolerance.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from typing import List, Sequence, Tuple

Point = Tuple[Fraction, Fraction]

# Targets: 1e-12 relative width, with an absolute floor so that a near-
# degenerate segment can still terminate.  Far below engineering
# resolution; de Casteljau subdivision converges geometrically.
REL_TOL = Fraction(1, 10 ** 12)
ABS_TOL = Fraction(1, 10 ** 12)
# Precision of each individual sqrt enclosure.
SQRT_EPS = Fraction(1, 10 ** 17)
# All leaf contributions are rounded outward onto multiples of GRID, so
# running totals never grow LCM-sized denominators.
GRID = Fraction(1, 10 ** 17)
MAX_DEPTH = 100

HALF = Fraction(1, 2)


@dataclass(frozen=True)
class ArcLengthBounds:
    """Rigorous enclosure of a segment's true arc length."""

    lower: Fraction
    upper: Fraction

    @property
    def error(self) -> Fraction:
        return self.upper - self.lower

    def relative_error(self) -> Fraction:
        if self.lower <= 0:
            return Fraction(0)
        return self.error / self.lower


def _as_point(p: Sequence) -> Point:
    return Fraction(p[0]), Fraction(p[1])


def _mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) * HALF, (a[1] + b[1]) * HALF)


def _dist2(a: Point, b: Point) -> Fraction:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def sqrt_bounds(x: Fraction, eps: Fraction = SQRT_EPS
                ) -> Tuple[Fraction, Fraction]:
    """Enclose ``sqrt(x)`` for rational ``x >= 0`` with width at most *eps*.

    ``sqrt(p/q) = sqrt(p*q)/q``; an integer scale ``M`` turns the integer
    ``floor(M*sqrt(p*q))`` into a rational enclosure.  Every decision is
    integer arithmetic, so the returned pair rigorously brackets the root.
    """
    if x < 0:
        raise ValueError("sqrt of negative rational")
    if x == 0:
        return Fraction(0), Fraction(0)
    p, q = x.numerator, x.denominator
    # 1/(q M) <= eps  =>  M >= ceil(1/(q eps)).
    need = Fraction(1) / (q * eps)
    m = max(1, (need.numerator + need.denominator - 1) // need.denominator)
    r = isqrt(p * q * m * m)
    lo = Fraction(r, q * m)
    if r * r == p * q * m * m:
        return lo, lo
    return lo, Fraction(r + 1, q * m)


def split_midpoint(points: Tuple[Point, Point, Point, Point]
                   ) -> Tuple[Tuple[Point, Point, Point, Point],
                              Tuple[Point, Point, Point, Point]]:
    """Exact de Casteljau split at t = 1/2 into (left, right) sub-curves."""
    p0, p1, p2, p3 = points
    q0 = _mid(p0, p1)
    q1 = _mid(p1, p2)
    q2 = _mid(p2, p3)
    r0 = _mid(q0, q1)
    r1 = _mid(q1, q2)
    s0 = _mid(r0, r1)
    return (p0, q0, r0, s0), (s0, r1, q2, p3)


def _poly_eval(p: Sequence[Fraction], t: Fraction) -> Fraction:
    r = Fraction(0)
    for c in reversed(p):
        r = r * t + c
    return r


def _poly_der(p: Sequence[Fraction]) -> List[Fraction]:
    return [Fraction(i) * p[i] for i in range(1, len(p))]


def speed_poly2(points: Tuple[Point, Point, Point, Point]) -> List[Fraction]:
    """Exact quartic coefficients of S(t) = |B'(t)|^2, constant first."""
    cx = [Fraction(p[0]) for p in points]
    cy = [Fraction(p[1]) for p in points]
    bx = [cx[0], 3 * (cx[1] - cx[0]),
          3 * (cx[0] - 2 * cx[1] + cx[2]),
          -cx[0] + 3 * cx[1] - 3 * cx[2] + cx[3]]
    by = [cy[0], 3 * (cy[1] - cy[0]),
          3 * (cy[0] - 2 * cy[1] + cy[2]),
          -cy[0] + 3 * cy[1] - 3 * cy[2] + cy[3]]
    vx, vy = _poly_der(bx), _poly_der(by)

    def mul(a: Sequence[Fraction], b: Sequence[Fraction]) -> List[Fraction]:
        out = [Fraction(0)] * (len(a) + len(b) - 1)
        for i, x in enumerate(a):
            for j, y in enumerate(b):
                out[i + j] += x * y
        return out

    s2 = [a + b for a, b in zip(mul(vx, vx), mul(vy, vy))]
    while s2 and s2[-1] == 0:
        s2.pop()
    return s2


def _geometric_bounds(points: Tuple[Point, Point, Point, Point]
                      ) -> Tuple[Fraction, Fraction]:
    """Rigorous (chord lower, control-polygon upper) outer enclosure."""
    p0, p1, p2, p3 = points
    chord_lo, _ = sqrt_bounds(_dist2(p0, p3))
    poly_hi = Fraction(0)
    for a, b in ((p0, p1), (p1, p2), (p2, p3)):
        _, edge_hi = sqrt_bounds(_dist2(a, b))
        poly_hi += edge_hi
    return chord_lo, poly_hi


def _derivative_bounds(s2: Sequence[Fraction], m: Fraction, half: Fraction
                       ) -> Tuple[List[Fraction], List[Fraction]]:
    """Exact lower/upper bounds of S, S', S'', S''' and S'''' on a leaf.

    Each is its finite Taylor expansion about the leaf midpoint, with the
    half-width substituted and every term accumulated by its absolute
    value.
    """
    poly = list(s2) + [Fraction(0)] * (5 - len(s2))
    dm: List[Fraction] = []
    for _ in range(5):
        dm.append(_poly_eval(poly, m))
        poly = _poly_der(poly)

    # S^(r)(t) = dm[r] + sum_{j>=1} (t-m)^j / j! * dm[r+j].  At the leaf
    # ends |t-m| <= half, so the absolute tail bounds every deviation.
    lows: List[Fraction] = []
    highs: List[Fraction] = []
    for r in range(5):
        tail = Fraction(0)
        term = Fraction(1)
        for j in range(1, 5 - r):
            term *= half / j
            tail += term * abs(dm[r + j])
        lows.append(dm[r] - tail)
        highs.append(dm[r] + tail)
    return lows, highs


def _simpson_bounds(s2: Sequence[Fraction], a: Fraction, b: Fraction,
                    speed_roots=sqrt_bounds) -> Tuple[Fraction, Fraction]:
    """Simpson enclosure of integral_a^b sqrt(S(t)) dt.

    The pair ``(-1, -1)`` signals that the certified speed on the leaf
    reaches zero (or the fourth-derivative bound is otherwise unusable);
    the caller then falls back to geometric bounds and subdivides.
    """
    h = b - a
    m = (a + b) * HALF
    lows, highs = _derivative_bounds(s2, m, h * HALF)
    if lows[0] <= 0:
        return Fraction(-1), Fraction(-1)

    root_lo, _ = sqrt_bounds(lows[0])
    s = lows[0]
    s3 = root_lo * s                 # lower bound on s^(3/2)
    s5 = s3 * s                      # s^(5/2)
    s7 = s5 * s                      # s^(7/2)
    # Certified upper bounds on |S^(r)| over the leaf (Taylor values may
    # be negative on either side).
    d1 = max(abs(lows[1]), abs(highs[1]))
    d2 = max(abs(lows[2]), abs(highs[2]))
    d3 = max(abs(lows[3]), abs(highs[3]))
    d4 = max(abs(lows[4]), abs(highs[4]))
    # |f''''| for f = sqrt(S):
    # f'''' = S''''/(2 f) - 3(S'S'''+S''^2)/(4 f^3)
    #        + 9 S'^2 S''/(4 f^5) - 15 S'^4/(16 f^7).
    # Every S derivative is replaced by its certified leaf maximum and
    # every power of f by its certified minimum, so this is an upper bound.
    f4 = d4 / (2 * root_lo)
    f4 += (3 * d1 * d3 + 3 * d2 * d2) / (4 * s3)
    f4 += Fraction(9, 4) * d1 * d1 * d2 / s5
    f4 += Fraction(15, 16) * d1 ** 4 / s7
    rem = h ** 5 * f4 / 2880

    fa_lo, fa_hi = speed_roots(_poly_eval(s2, a))
    fm_lo, fm_hi = speed_roots(_poly_eval(s2, m))
    fb_lo, fb_hi = speed_roots(_poly_eval(s2, b))
    width = h / 6
    return (width * (fa_lo + 4 * fm_lo + fb_lo) - rem,
            width * (fa_hi + 4 * fm_hi + fb_hi) + rem)


def _grid_out(lo: Fraction, hi: Fraction) -> Tuple[Fraction, Fraction]:
    """Round an interval outward onto multiples of GRID (exact)."""
    d = GRID.denominator
    glo = Fraction((lo.numerator * d) // lo.denominator, d)
    ghi = Fraction((hi.numerator * d + hi.denominator - 1)
                   // hi.denominator, d)
    return glo, ghi


def _bounds_unit(points: Tuple[Point, Point, Point, Point],
                 rel_tol: Fraction, abs_tol: Fraction) -> ArcLengthBounds:
    """Adaptive enclosure for an already-scale-normalised segment."""
    s2 = speed_poly2(points)
    # De Casteljau splitting puts every leaf endpoint on a dyadic grid;
    # each distinct speed-squared value is therefore sqrt-enclosed only
    # once and shared by the leaves on both sides of it.
    root_cache: dict[Fraction, Tuple[Fraction, Fraction]] = {}

    def speed_roots(s: Fraction) -> Tuple[Fraction, Fraction]:
        cached = root_cache.get(s)
        if cached is None:
            cached = sqrt_bounds(s)
            root_cache[s] = cached
        return cached

    def leaf(a: Fraction, b: Fraction,
             node: Tuple[Point, Point, Point, Point]
             ) -> Tuple[Fraction, Fraction]:
        # The Simpson enclosure with its exact remainder is rigorous on its
        # own; the geometric chord/polygon bounds are only needed for leaves
        # whose certified speed reaches zero (possible cusp).
        t_lo, t_hi = _simpson_bounds(s2, a, b, speed_roots)
        if t_lo >= 0:
            return t_lo, t_hi
        return _geometric_bounds(node)

    a0, b0 = Fraction(0), Fraction(1)
    lo0, hi0 = _grid_out(*leaf(a0, b0, points))

    # Heap entries: (-gap, tie, a, b, points, depth, lo, hi)
    counter = 0
    heap: List[Tuple[Fraction, int, Fraction, Fraction,
                     Tuple[Point, Point, Point, Point], int,
                     Fraction, Fraction]] = []
    heapq.heappush(
        heap, (-(hi0 - lo0), counter, a0, b0, points, 0, lo0, hi0))
    total_lo, total_hi = lo0, hi0

    def good_enough() -> bool:
        return total_hi - total_lo <= rel_tol * total_lo + abs_tol

    while heap and not good_enough():
        _, _, a, b, node, depth, lo, hi = heapq.heappop(heap)
        if depth >= MAX_DEPTH:
            continue  # retire: its bounds remain in the running totals
        total_lo -= lo
        total_hi -= hi
        m = (a + b) * HALF
        left, right = split_midpoint(node)
        for (ca, cb, child) in ((a, m, left), (m, b, right)):
            clo, chi = _grid_out(*leaf(ca, cb, child))
            total_lo += clo
            total_hi += chi
            counter += 1
            heapq.heappush(
                heap, (-(chi - clo), counter, ca, cb, child,
                       depth + 1, clo, chi))

    return ArcLengthBounds(total_lo, total_hi)


def arc_length_bounds(points: Sequence[Sequence],
                      rel_tol: Fraction = REL_TOL,
                      abs_tol: Fraction = ABS_TOL) -> ArcLengthBounds:
    """Adaptively enclose the true arc length of one cubic Bezier segment.

    Coordinates are translated to the origin and divided by the exact
    integer coordinate span before subdivision: arc length is homogeneous
    under a common scale, and unit-scale data keeps the certified
    fourth-derivative remainder tight for any input dimensions.  Leaves
    live in a priority queue keyed by enclosure width; the widest leaf is
    split next and subdivision stops once the summed certified width is no
    greater than ``rel_tol * lower + abs_tol``.  The returned ``error`` is
    the exact rational interval width.  A per-leaf depth cap bounds the
    work for pathological input, and the remaining leaves always make a
    valid enclosure.
    """
    raw: List[Point] = [_as_point(p) for p in points]
    min_x = min(p[0] for p in raw)
    max_x = max(p[0] for p in raw)
    min_y = min(p[1] for p in raw)
    max_y = max(p[1] for p in raw)
    span = max(max_x - min_x, max_y - min_y)
    if span == 0:
        return ArcLengthBounds(Fraction(0), Fraction(0))

    unit: Tuple[Point, Point, Point, Point] = tuple(  # type: ignore[assignment]
        ((x - min_x) / span, (y - min_y) / span) for x, y in raw
    )  # type: ignore[arg-type]
    inner = _bounds_unit(unit, rel_tol, abs_tol / span)
    return ArcLengthBounds(inner.lower * span, inner.upper * span)
