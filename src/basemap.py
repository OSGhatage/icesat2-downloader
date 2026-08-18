"""One-shot tile mosaic for PNG exports. No startup provider marathon."""

from __future__ import annotations

import io
import math
from typing import Optional

import numpy as np
from PIL import Image

from src.config import USER_AGENT
from src.geo import Bounds
from src.http import make_session

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAX_TILES = 36


def _lon_to_x(lon: float, z: int) -> int:
    return int((lon + 180.0) / 360.0 * 2**z)


def _lat_to_y(lat: float, z: int) -> int:
    lat = min(85.0511, max(-85.0511, lat))
    r = math.radians(lat)
    return int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * 2**z)


def _x_to_lon(x: float, z: int) -> float:
    return x / 2**z * 360.0 - 180.0


def _y_to_lat(y: float, z: int) -> float:
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2**z))))


def _auto_zoom(bounds: Bounds) -> int:
    w, s, e, n = bounds
    span = max(n - s, e - w)
    for thresh, z in (
        (0.02, 13),
        (0.05, 12),
        (0.1, 11),
        (0.25, 10),
        (0.5, 9),
        (1.0, 8),
        (2.0, 7),
    ):
        if span < thresh:
            return z
    return 6


def fetch_basemap(bounds: Bounds, log=print) -> tuple[Optional[np.ndarray], Optional[list[float]]]:
    w, s, e, n = bounds
    session = make_session()
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.openstreetmap.org/"}

    for name, template in (("Esri imagery", ESRI), ("OSM", OSM)):
        zoom = _auto_zoom(bounds)
        while True:
            mx = 2**zoom - 1
            x1, x2 = _lon_to_x(w, zoom), _lon_to_x(e, zoom)
            y1, y2 = _lat_to_y(n, zoom), _lat_to_y(s, zoom)
            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1
            x1, x2 = max(0, x1), min(mx, x2)
            y1, y2 = max(0, y1), min(mx, y2)
            total = (x2 - x1 + 1) * (y2 - y1 + 1)
            if total <= MAX_TILES or zoom <= 4:
                break
            zoom -= 1

        tiles = {}
        for ty in range(y1, y2 + 1):
            for tx in range(x1, x2 + 1):
                url = template.format(z=zoom, x=tx, y=ty)
                try:
                    resp = session.get(url, headers=headers, timeout=10)
                    data = resp.content
                    png = data[:8] == b"\x89PNG\r\n\x1a\n"
                    jpg = data[:2] == b"\xff\xd8"
                    if resp.status_code == 200 and (png or jpg) and len(data) > 400:
                        tiles[(tx, ty)] = data
                except Exception:
                    continue

        if len(tiles) < max(1, int(total * 0.4)):
            log(f"  {name}: {len(tiles)}/{total} tiles — trying next")
            continue

        ts = 256
        canvas = Image.new("RGB", ((x2 - x1 + 1) * ts, (y2 - y1 + 1) * ts), (200, 200, 200))
        for (tx, ty), data in tiles.items():
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB").resize((ts, ts))
                canvas.paste(img, ((tx - x1) * ts, (ty - y1) * ts))
            except Exception:
                continue
        arr = np.asarray(canvas)
        extent = [
            _x_to_lon(x1, zoom),
            _x_to_lon(x2 + 1, zoom),
            _y_to_lat(y2 + 1, zoom),
            _y_to_lat(y1, zoom),
        ]
        log(f"  basemap: {name} {len(tiles)}/{total} tiles @ z{zoom}")
        return arr, extent

    log("  basemap unavailable — PNGs will use a plain grid")
    return None, None
