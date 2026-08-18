"""Nominatim place search. Public API, 1 request at a time."""

from __future__ import annotations

from src.config import NOMINATIM_URL, USER_AGENT
from src.geo import Bounds, normalize_bounds
from src.http import make_session


def search_place(query: str) -> dict | None:
    query = (query or "").strip()
    if not query:
        return None

    # "lat, lon" shortcut
    if "," in query:
        parts = [p.strip() for p in query.split(",")]
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return {
                        "name": f"{lat:.4f}, {lon:.4f}",
                        "lat": lat,
                        "lon": lon,
                        "bounds": None,
                    }
            except ValueError:
                pass

    resp = make_session().get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    row = rows[0]
    lat, lon = float(row["lat"]), float(row["lon"])
    bbox = row.get("boundingbox")
    bounds: Bounds | None = None
    if bbox and len(bbox) == 4:
        south, north, west, east = map(float, bbox)
        bounds = normalize_bounds(west, south, east, north)
    return {
        "name": row.get("display_name", query),
        "lat": lat,
        "lon": lon,
        "bounds": bounds,
    }
