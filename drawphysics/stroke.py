"""Freehand stroke capture and simplification helpers."""
from __future__ import annotations

import math

import numpy as np
from scipy.interpolate import splev, splprep

Point = tuple[float, float]


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def min_distance_filter(points: list[Point], min_distance: float) -> list[Point]:
    """Drop points that are closer than min_distance to the last kept point."""
    if not points:
        return []
    kept = [points[0]]
    for p in points[1:]:
        if dist(kept[-1], p) >= min_distance:
            kept.append(p)
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def _perpendicular_distance(point: Point, line_start: Point, line_end: Point) -> float:
    if line_start == line_end:
        return dist(point, line_start)
    x0, y0 = point
    x1, y1 = line_start
    x2, y2 = line_end
    num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    den = math.hypot(y2 - y1, x2 - x1)
    return num / den


def douglas_peucker(points: list[Point], tolerance: float) -> list[Point]:
    if len(points) < 3:
        return points[:]

    dmax = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        d = _perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            dmax = d
            index = i

    if dmax > tolerance:
        left = douglas_peucker(points[: index + 1], tolerance)
        right = douglas_peucker(points[index:], tolerance)
        return left[:-1] + right
    return [points[0], points[-1]]


def is_closed_loop(points: list[Point], threshold: float) -> bool:
    if len(points) < 3:
        return False
    return dist(points[0], points[-1]) <= threshold


def bounding_extent(points: list[Point]) -> float:
    if not points:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def polygon_area(points: list[Point]) -> float:
    """Signed area via shoelace formula (positive = counter-clockwise in math coords)."""
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def centroid(points: list[Point]) -> Point:
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    return (cx, cy)


def smooth_stroke(points: list[Point], closed: bool, tolerance: float, num_samples: int = 200) -> list[Point]:
    """Stage 1: fit a smooth cubic B-spline through the (min-distance-filtered)
    raw stroke points and resample it densely.

    `tolerance` bounds how far the fitted curve is allowed to deviate from
    the original points (scipy's smoothing parameter s is in units of summed
    squared deviation, s ~= m * tolerance**2, so tolerance stays an
    intuitive "pixels of allowed wobble" knob). A hand-drawn circle's facets
    and jitter get smoothed away here; a genuine corner survives because the
    spline still has to pass close to every point overall, it just isn't
    forced through each one exactly.

    For a closed loop, fits a periodic spline (no seam/kink where the
    stroke closes). Falls back to returning the input unchanged if there
    aren't enough distinct points to fit a cubic spline.
    """
    pts = points[:-1] if closed and points[0] == points[-1] else points[:]
    min_points_needed = 4 if closed else 4
    if len(pts) < min_points_needed:
        return points

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    if closed:
        xs = xs + [xs[0]]
        ys = ys + [ys[0]]

    m = len(xs)
    smoothing = m * (tolerance**2)

    try:
        tck, _u = splprep([xs, ys], s=smoothing, per=1 if closed else 0, k=3)
    except Exception:
        return points

    u_fine = np.linspace(0, 1, num_samples)
    x_fine, y_fine = splev(u_fine, tck)
    smoothed = list(zip(x_fine.tolist(), y_fine.tolist()))

    if closed:
        smoothed.append(smoothed[0])

    return smoothed


def fit_lines_to_curve(points: list[Point], tolerance: float) -> list[Point]:
    """Stage 2: convert a dense smooth curve (e.g. from smooth_stroke) into
    an efficient set of straight line segments that still hug the curve
    closely. Reuses Douglas-Peucker with a separate, normally much smaller,
    tolerance than the smoothing stage so the polyline is visually
    indistinguishable from the curve it approximates."""
    if len(points) < 3:
        return points[:]
    return douglas_peucker(points, tolerance)
