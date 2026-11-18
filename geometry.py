"""Pure geometry helpers used by the annotation comparison tool.

This module contains no JSON, file-name or reporting logic.  All areas are in
square pixels and all coordinates are absolute image coordinates.
"""

from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry import Polygon
from shapely.validation import explain_validity

Point = tuple[float, float]


def shoelace_area(points: Sequence[Point]) -> float:
    """Return the absolute area of a ring using the Gauss shoelace formula."""
    pts: list[Point] = []
    for x, y in points:
        pts.append((float(x), float(y)))
    if len(pts) < 3:
        return 0.0
    doubled = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        doubled += x1 * y2 - x2 * y1
    return abs(doubled) / 2.0


def polygon_from_points(points: Sequence[Point]) -> Polygon | None:
    """Build a polygon from a ring; ``None`` if fewer than 3 distinct vertices."""
    pts: list[Point] = [(float(x), float(y)) for x, y in points]
    if len(set(pts)) < 3:
        return None
    try:
        return Polygon(pts)
    except (TypeError, ValueError):
        return None


def polygon_from_bbox(x1: float, y1: float, x2: float, y2: float) -> Polygon:
    """Build an axis-aligned rectangle, normalizing the corners with min/max."""
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    return Polygon(
        [
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        ]
    )


def intersection_area(a: Polygon, b: Polygon) -> float:
    """Area of ``a AND b``."""
    return float(a.intersection(b).area)


def union_area(a: Polygon, b: Polygon) -> float:
    """Area of ``a OR b`` (the combined figure, not the sum of both areas)."""
    return float(a.union(b).area)


def pair_score(a: Polygon, b: Polygon) -> tuple[float, float, float]:
    """Return ``(score, I, U)`` with areas unrounded; score is 0.0 when U == 0."""
    i = intersection_area(a, b)
    u = union_area(a, b)
    score = i / u if u != 0 else 0.0
    return score, i, u


def is_valid(polygon: Polygon) -> tuple[bool, str]:
    """Return ``(is_valid, shapely reason or empty string)``."""
    if polygon is None:
        return False, "no polygon"
    if not polygon.is_valid:
        return False, explain_validity(polygon)
    if polygon.area == 0:
        return False, "zero area"
    return True, ""
