"""AOI helpers and OpenAltimetry span limits."""

from __future__ import annotations

import math
from typing import Optional

from src.config import OA_MAX_SPAN


Bounds = tuple[float, float, float, float]  # west, south, east, north


def normalize_bounds(west: float, south: float, east: float, north: float) -> Bounds:
    if west > east:
        west, east = east, west
    if south > north:
        south, north = north, south
    return (
        max(-180.0, min(180.0, west)),
        max(-90.0, min(90.0, south)),
        max(-180.0, min(180.0, east)),
        max(-90.0, min(90.0, north)),
    )


def spans_deg(bounds: Bounds) -> tuple[float, float]:
    w, s, e, n = bounds
    return (e - w), (n - s)


def area_km2(bounds: Bounds) -> float:
    w, s, e, n = bounds
    lat_km = (n - s) * 111.0
    lon_km = (e - w) * 111.0 * math.cos(math.radians((n + s) / 2.0))
    return abs(lat_km * lon_km)


def max_span_for(product: str, sampling: bool = False) -> float:
    if product == "ATL03" and sampling:
        return OA_MAX_SPAN["DEFAULT"]
    return OA_MAX_SPAN.get(product, OA_MAX_SPAN["DEFAULT"])


def validate_aoi(product: str, bounds: Bounds, sampling: bool = False) -> Optional[str]:
    dx, dy = spans_deg(bounds)
    if dx <= 0 or dy <= 0:
        return "AOI has zero width or height."
    limit = max_span_for(product, sampling)
    if dx > limit or dy > limit:
        extra = " Enable ATL03 sampling (1/1000) to allow up to 5°." if product == "ATL03" and not sampling else ""
        return (
            f"{product} OpenAltimetry limit is {limit:.0f}° × {limit:.0f}°. "
            f"Your box is {dx:.2f}° × {dy:.2f}°.{extra}"
        )
    return None


def bounds_from_polygon(coords: list) -> Optional[Bounds]:
    """coords: list of [lon, lat] rings (GeoJSON)."""
    if not coords:
        return None
    ring = coords[0] if isinstance(coords[0][0], (list, tuple)) else coords
    lons = [float(p[0]) for p in ring]
    lats = [float(p[1]) for p in ring]
    if not lons or not lats:
        return None
    return normalize_bounds(min(lons), min(lats), max(lons), max(lats))
