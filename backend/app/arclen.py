"""Certified true-arc-length enclosures for cubic-Bezier segments.

The anti-corrosion travel review must use the *continuous real arc
length* of each cubic segment

    L = ∫₀¹ ‖B'(t)‖ dt = ∫₀¹ √Q(t) dt,

where ``Q(t) = |B'(t)|²`` is the speed-squared quartic with integer
coefficients (see :class:`app.geometry.Segment`).  The integral is
generally elliptic, so it cannot be evaluated in closed form; replacing
it by the control-polygon length, screen pixels or a fixed-parameter
sample is explicitly forbidden.  Instead this module returns a
**convergent rational enclosure** ``[lower, upper]`` with a rigorous
error bound:

* a genuinely zero tangent vector (where √Q is not C⁴ and no Simpson
  remainder exists) is detected exactly by isolating the real roots of
  the integer quartic ``Q`` via Vincent-Descartes (:mod:`app.polyroot`);
  audit-passing drafts have none;
* square roots are enclosed by rational bounds derived from
  :func:`math.isqrt`, so no floating-point rounding can escape the
  enclosure;
* a bound ``M₄ ≥ sup|(√Q)⁽⁴⁾|`` is tabulated over a fixed dyadic panel
  grid from the closed-form fourth derivative (Faà di Bruno) evaluated
  by interval arithmetic (a single [0,1] interval would be far too
  loose from correlated terms such as ``Q'⁴/S⁷``).  Each leaf [a,b]
  carries the rigorous Simpson remainder ``(b-a)⁵/2880 · M₄``: coarse
  leaves reuse the tabulated panel bound, leaves narrower than a panel
  get a tight bound on their own interval.  Leaves are bisected, widest
  enclosure first, until the enclosure meets the requested tolerance;
* on an interval whose enclosure of ``Q`` still touches zero, only the
  coarser but sound bound ``(b-a)·[√q_lo, √q_hi]`` is used until
  refinement proves ``Q > 0`` there.

Simpson is exact for polynomials up to degree three, hence constant-
speed straight runs converge with a single leaf.  Every step uses exact
rational arithmetic apart from the integer square root; the process is
deterministic, so the reported bounds are stable for a fixed draft.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

# Absolute rational granularity for sqrt point enclosures.  2^-70 is far
# below every engineering tolerance used for certification.
_SQRT_BITS = 70
_SQRT_K = 1 << _SQRT_BITS

Interval = Tuple[Fraction, Fraction]


@dataclass(frozen=True)
class ArcLengthBounds:
    """Rigorous enclosure of a segment arc length over [0, 1]."""

    lower: Fraction
    upper: Fraction
    converged: bool
    subdivisions: int

    @property
    def error(self) -> Fraction:
        return self.upper - self.lower


# --------------------------------------------------------------------------
# Interval arithmetic (all endpoints exact Fractions; t-intervals >= 0)
# --------------------------------------------------------------------------

def _iadd(a: Interval, b: Interval) -> Interval:
    return a[0] + b[0], a[1] + b[1]


def _imul(a: Interval, b: Interval) -> Interval:
    vals = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
    return min(vals), max(vals)


def _iscale(c: Fraction, a: Interval) -> Interval:
    if c >= 0:
        return c * a[0], c * a[1]
    return c * a[1], c * a[0]


def _ipow(a: Interval, k: int) -> Interval:
    """Integer power for an arbitrary interval (handles zero-straddling)."""
    if k % 2 == 1:
        return a[0] ** k, a[1] ** k
    lo, hi = a
    if lo >= 0:
        return lo ** k, hi ** k
    if hi <= 0:
        return hi ** k, lo ** k
    return Fraction(0), max(-lo, hi) ** k


def _irecip_pos(a: Interval) -> Interval:
    return 1 / a[1], 1 / a[0]


def sqrt_bounds(x: Fraction, bits: int = _SQRT_BITS) -> Interval:
    """Rational enclosure  lo ≤ √x < hi  with  hi - lo = 2^-bits.

    With ``m = ⌊√(⌊x·2^(2bits)⌋)⌋`` the integer square-root identity
    gives ``m ≤ √x·2^bits < m+1``.
    """
    k = 1 << bits
    m = math.isqrt(x.numerator * k * k // x.denominator)
    return Fraction(m, k), Fraction(m + 1, k)


# Derivative bounds only steer the adaptive remainder; they never need
# point-enclosure precision.  A coarser sqrt grid keeps the nested
# s^-7 fractions small while staying ~1e-14 tight.
_DERIV_BITS = 48
# M4 bounds are rounded up onto this rational grid afterwards (still a
# rigorous upper bound), bounding big-integer sizes in leaf remainders.
_M4_GRID_BITS = 96


def _round_up(x: Fraction) -> Fraction:
    scale = 1 << _M4_GRID_BITS
    return Fraction(-((-x.numerator) * scale // x.denominator), scale)


def _interval_horner(p: Sequence[Fraction], t: Interval) -> Interval:
    """Rigorous range of polynomial p over t (t_lo, t_hi >= 0).

    Plain Horner is invalid once the running interval straddles zero:
    multiplying a negative low endpoint by the t-interval reverses its
    endpoints, so both sign cases are handled explicitly.
    """
    lo = hi = Fraction(0)
    tlo, thi = t
    for c in reversed(p):
        nlo = lo * tlo if lo >= 0 else lo * thi
        nhi = hi * thi if hi >= 0 else hi * tlo
        lo, hi = nlo + c, nhi + c
    return lo, hi


def _derivatives(q: Sequence[Fraction]) -> List[List[Fraction]]:
    """Q', Q'', Q''', Q'''' as exact rational coefficient lists."""
    ders: List[List[Fraction]] = []
    cur = list(q)
    for _ in range(4):
        cur = [i * cur[i] for i in range(1, len(cur))] or [Fraction(0)]
        ders.append(cur)
    return ders


def _f4_over(qders: Sequence[Sequence[Fraction]], s: Interval,
             t: Interval) -> Fraction:
    """Rigorous bound on |(√Q)⁽⁴⁾| given a positive enclosure s of √Q.

    Faà di Bruno for f(t) = √Q(t), writing q_i = Q⁽ⁱ⁾:

        f⁽⁴⁾ = q4/(2s) − (4 q1 q3 + 3 q2²)/(4 s³)
               + 9 q1² q2/(4 s⁵) − 15 q1⁴/(16 s⁷).
    """
    q1, q2, q3, q4 = (_interval_horner(p, t) for p in qders)
    s1 = _irecip_pos(s)
    term1 = _iscale(Fraction(1, 2), _imul(q4, s1))
    inner = _iadd(_iscale(4, _imul(q1, q3)),
                  _iscale(3, _ipow(q2, 2)))
    term2 = _iscale(-Fraction(1, 4),
                    _imul(inner, _ipow(s1, 3)))
    term3 = _iscale(Fraction(9, 4),
                    _imul(_imul(_ipow(q1, 2), q2),
                          _ipow(s1, 5)))
    term4 = _iscale(-Fraction(15, 16),
                    _imul(_ipow(q1, 4), _ipow(s1, 7)))
    f4 = _iadd(_iadd(_iadd(term1, term2), term3), term4)
    return _round_up(max(-f4[0], f4[1]))


def _point_speed_bounds(q: Sequence[Fraction], t: Fraction) -> Interval:
    """Rational enclosure of √Q(t) at one exact parameter."""
    value = Fraction(0)
    for c in reversed(q):
        value = value * t + c
    if value == 0:
        return Fraction(0), Fraction(1, _SQRT_K)
    return sqrt_bounds(value)


# --------------------------------------------------------------------------
# Adaptive Simpson enclosure
# --------------------------------------------------------------------------

# Derivative bounds are tabulated over a fixed dyadic panel grid: 2^6
# panels narrow the interval-arithmetic overestimation enough, and
# bisection keeps every leaf panel-aligned (it intersects either one
# panel or two consecutive ones).
_PANEL_BITS = 6
_PANELS = 1 << _PANEL_BITS


@dataclass
class _Leaf:
    a: Fraction
    b: Fraction
    f_a: Interval
    f_m: Interval
    f_b: Interval
    depth: int

    def contrib(self, m4: Optional[Fraction],
                qrange: Optional[Interval]) -> Tuple[Fraction, Fraction]:
        """Rigorous [lower, upper] contribution of this leaf."""
        w = self.b - self.a
        if m4 is not None:
            s_lo = w / 6 * (self.f_a[0] + 4 * self.f_m[0] + self.f_b[0])
            s_hi = w / 6 * (self.f_a[1] + 4 * self.f_m[1] + self.f_b[1])
            remainder = w ** 5 * m4 / 2880
            return max(Fraction(0), s_lo - remainder), s_hi + remainder
        # Coarse sound fallback (only on panels where Q may touch zero):
        # sqrt is monotone, so f lies inside [sqrt(q_lo), sqrt(q_hi)].
        assert qrange is not None
        return w * sqrt_bounds(max(Fraction(0), qrange[0]))[0], \
            w * sqrt_bounds(qrange[1])[1]


def _panel_bounds(q: Sequence[Fraction],
                  qders: Sequence[Sequence[Fraction]]
                  ) -> List[Optional[Fraction]]:
    """Per-panel rigorous |(√Q)⁽⁴⁾| bound; None where Q may touch zero."""
    bounds: List[Optional[Fraction]] = []
    for i in range(_PANELS):
        t = (Fraction(i, _PANELS), Fraction(i + 1, _PANELS))
        qlo, qhi = _interval_horner(q, t)
        if qlo <= 0:
            bounds.append(None)
            continue
        s = (sqrt_bounds(qlo, _DERIV_BITS)[0],
             sqrt_bounds(qhi, _DERIV_BITS)[1])
        bounds.append(_f4_over(qders, s, t))
    return bounds


def arc_length_bounds(seg, rel_tol: Fraction = Fraction(1, 10 ** 10),
                      abs_tol: Fraction = Fraction(1, 10 ** 11),
                      max_depth: int = 40) -> ArcLengthBounds:
    """Compute the convergent arc-length enclosure of one segment.

    The stop criterion compares the enclosure width with
    ``abs_tol + rel_tol · lower``.  ``converged`` is False only if the
    depth/leaf budget is exhausted first (defensive for the integer
    quartics arising here).
    """
    q_int = list(seg.speed2)
    while q_int and q_int[-1] == 0:
        q_int.pop()
    if not q_int:  # identically zero tangent vector
        return ArcLengthBounds(Fraction(0), Fraction(0), True, 0)
    q = [Fraction(c) for c in q_int]
    qders = _derivatives(q)

    # Exact test for a genuinely zero tangent vector (roots of the
    # integer quartic Q, found by Vincent-Descartes isolation).  If Q
    # touches zero, sqrt Q is not C4 and no convergent enclosure exists;
    # the audit rejects such drafts before a review, but direct callers
    # get a cheap, still-rigorous outer bound instead of refining
    # forever.  A merely *loose* interval-Horner lower bound is not a
    # root: such panels are refined adaptively until Q proves positive.
    if seg.zero_speed_params():
        _, qhi = _interval_horner(q, (Fraction(0), Fraction(1)))
        return ArcLengthBounds(Fraction(0), sqrt_bounds(qhi)[1],
                               False, 0)

    panel_m4 = _panel_bounds(q, qders)

    def m4_for(a: Fraction, b: Fraction) -> Optional[Fraction]:
        """Rigorous |(√Q)⁽⁴⁾| bound over [a, b].

        Coarse leaves reuse a precomputed panel bound (cheap, possibly
        loose); leaves narrower than a panel are evaluated on their own
        interval, where interval arithmetic is tight and the dyadic
        denominators keep the exact arithmetic cheap.  Every split is
        dyadic and panel-aligned, so a sub-panel leaf never crosses a
        panel boundary.
        """
        w = b - a
        if w >= 1:
            touched = panel_m4
        elif w >= Fraction(1, _PANELS):
            ia = max(0, int(a * _PANELS))
            ib = min(_PANELS, int(b * _PANELS) + 1)
            touched = panel_m4[ia:ib]
        else:
            qlo, qhi = _interval_horner(q, (a, b))
            if qlo <= 0:
                return None
            s = (sqrt_bounds(qlo, _DERIV_BITS)[0],
                 sqrt_bounds(qhi, _DERIV_BITS)[1])
            return _f4_over(qders, s, (a, b))
        if any(m is None for m in touched):
            return None
        return max(m for m in touched)  # type: ignore[type-var]

    def make_leaf(a: Fraction, b: Fraction, f_a: Interval,
                  f_b: Interval, depth: int
                  ) -> Tuple[_Leaf, Optional[Fraction], Optional[Interval]]:
        m = (a + b) / 2
        leaf = _Leaf(a, b, f_a, _point_speed_bounds(q, m), f_b, depth)
        m4 = m4_for(a, b)
        qr = None if m4 is not None else _interval_horner(q, (a, b))
        return leaf, m4, qr

    root, root_m4, root_qr = make_leaf(
        Fraction(0), Fraction(1),
        _point_speed_bounds(q, Fraction(0)),
        _point_speed_bounds(q, Fraction(1)), 0)
    lo, hi = root.contrib(root_m4, root_qr)
    total_lo, total_hi = lo, hi

    # Heap of (gap descending, insertion order, leaf, m4, qrange).
    heap: List[Tuple[Fraction, int, _Leaf, Optional[Fraction],
                     Optional[Interval]]] = []
    counter = 0
    heapq.heappush(heap, (-(hi - lo), counter, root, root_m4, root_qr))
    subdivisions = 0
    n_leaves = 1
    converged = True

    while total_hi - total_lo > abs_tol + rel_tol * max(Fraction(0), total_lo):
        neg_gap, _, leaf, leaf_m4, leaf_qr = heapq.heappop(heap)
        old_lo, old_hi = leaf.contrib(leaf_m4, leaf_qr)
        if leaf.depth >= max_depth or n_leaves > 100_000:
            heapq.heappush(
                heap, (neg_gap, counter, leaf, leaf_m4, leaf_qr))
            counter += 1
            converged = False
            break

        m = (leaf.a + leaf.b) / 2
        left, lm4, lqr = make_leaf(leaf.a, m, leaf.f_a, leaf.f_m,
                                   leaf.depth + 1)
        right, rm4, rqr = make_leaf(m, leaf.b, leaf.f_m, leaf.f_b,
                                    leaf.depth + 1)
        l_lo, l_hi = left.contrib(lm4, lqr)
        r_lo, r_hi = right.contrib(rm4, rqr)
        total_lo += l_lo + r_lo - old_lo
        total_hi += l_hi + r_hi - old_hi
        heapq.heappush(heap, (-(l_hi - l_lo), counter, left, lm4, lqr))
        heapq.heappush(heap, (-(r_hi - r_lo), counter + 1, right, rm4, rqr))
        counter += 2
        subdivisions += 1
        n_leaves += 1

    return ArcLengthBounds(max(Fraction(0), total_lo), total_hi,
                           converged, subdivisions)
