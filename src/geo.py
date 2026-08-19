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


def pad_bounds(bounds: Bounds, frac: float = 0.05) -> Bounds:
    w, s, e, n = bounds
    dx = max((e - w) * frac, 0.008)
    dy = max((n - s) * frac, 0.008)
    return normalize_bounds(w - dx, s - dy, e + dx, n + dy)


def bounds_from_points(lons, lats, frac: float = 0.06) -> Optional[Bounds]:
    if lons is None or lats is None:
        return None
    lons = list(lons)
    lats = list(lats)
    if not lons or not lats:
        return None
    return pad_bounds(normalize_bounds(min(lons), min(lats), max(lons), max(lats)), frac)


def parse_cmr_polygon(poly_str: str) -> list[tuple[float, float]]:
    """CMR stores 'lat lon lat lon ...'. Returns [(lat, lon), ...]."""
    nums = [float(x) for x in str(poly_str).split()]
    out: list[tuple[float, float]] = []
    for i in range(0, len(nums) - 1, 2):
        out.append((nums[i], nums[i + 1]))
    return out


def _sample_ring_in_box(
    latlon: list[tuple[float, float]],
    bounds: Bounds,
    pad: float,
) -> list[list[float]]:
    """Fallback when shapely is missing: sample edges and keep points in the AOI."""
    w, s, e, n = bounds
    w, s, e, n = w - pad, s - pad, e + pad, n + pad
    pts: list[list[float]] = []
    ring = list(latlon)
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    for (a1, o1), (a2, o2) in zip(ring, ring[1:]):
        steps = 24
        for t in range(steps + 1):
            f = t / steps
            lat = a1 + f * (a2 - a1)
            lon = o1 + f * (o2 - o1)
            if s <= lat <= n and w <= lon <= e:
                pts.append([lat, lon])
    if len(pts) < 2:
        return []
    # thin strip → a single north-south line looks cleaner
    pts.sort(key=lambda p: p[0])
    slim: list[list[float]] = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - slim[-1][0]) > 1e-5 or abs(p[1] - slim[-1][1]) > 1e-5:
            slim.append(p)
    return slim


def clip_ring_to_aoi(
    latlon: list[tuple[float, float]],
    bounds: Bounds,
    pad: float = 0.03,
) -> list[list[list[float]]]:
    """Clip a CMR granule polygon to the AOI.

    Returns Folium-ready rings: [[[lat, lon], ...], ...].
    """
    if not latlon or len(latlon) < 2:
        return []

    try:
        from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box

        w, s, e, n = bounds
        aoi = box(w - pad, s - pad, e + pad, n + pad)
        coords = [(lon, lat) for lat, lon in latlon]
        geom = Polygon(coords) if len(coords) >= 3 else LineString(coords)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            geom = LineString(coords)
        clipped = geom.intersection(aoi)
        if clipped.is_empty:
            sampled = _sample_ring_in_box(latlon, bounds, pad)
            return [sampled] if sampled else []

        rings: list[list[list[float]]] = []

        def _ring_from_poly(poly: Polygon) -> None:
            ring = [[lat, lon] for lon, lat in poly.exterior.coords]
            if len(ring) >= 2:
                rings.append(ring)

        def _line(line: LineString) -> None:
            ring = [[lat, lon] for lon, lat in line.coords]
            if len(ring) >= 2:
                rings.append(ring)

        if isinstance(clipped, Polygon):
            _ring_from_poly(clipped)
        elif isinstance(clipped, MultiPolygon):
            for part in clipped.geoms:
                _ring_from_poly(part)
        elif isinstance(clipped, LineString):
            _line(clipped)
        elif isinstance(clipped, MultiLineString):
            for part in clipped.geoms:
                _line(part)
        return rings or ([_sample_ring_in_box(latlon, bounds, pad)] if _sample_ring_in_box(latlon, bounds, pad) else [])
    except Exception:
        sampled = _sample_ring_in_box(latlon, bounds, pad)
        return [sampled] if sampled else []
