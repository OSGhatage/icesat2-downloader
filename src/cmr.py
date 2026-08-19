"""NASA CMR granule search — public, no login."""

from __future__ import annotations

import re
from typing import Callable

from src.config import CMR_GRANULES_URL
from src.geo import Bounds, clip_ring_to_aoi, parse_cmr_polygon
from src.http import make_session

# ATL03_20181014005222_02350101_006_02.h5
GRANULE_RE = re.compile(
    r"(?P<product>ATL\d{2})_"
    r"(?P<yyyymmdd>\d{8})\d{6}_"
    r"(?P<rgt>\d{4})(?P<cycle>\d{2})\d{2}",
    re.IGNORECASE,
)


def parse_granule_title(title: str) -> dict | None:
    match = GRANULE_RE.search(title or "")
    if not match:
        return None
    ymd = match.group("yyyymmdd")
    return {
        "product": match.group("product").upper(),
        "rgt": int(match.group("rgt")),
        "cycle": int(match.group("cycle")),
        "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
        "title": title,
    }


def search_granules(
    product: str,
    bounds: Bounds,
    date_start: str,
    date_end: str,
    log: Callable[[str], None] = print,
) -> list[dict]:
    west, south, east, north = bounds
    session = make_session()
    found: list[dict] = []
    seen: set[str] = set()
    page = 1

    while True:
        resp = session.get(
            CMR_GRANULES_URL,
            params={
                "short_name": product,
                "bounding_box": f"{west},{south},{east},{north}",
                "temporal": f"{date_start}T00:00:00Z,{date_end}T23:59:59Z",
                "page_size": 200,
                "page_num": page,
                "sort_key": "start_date",
            },
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"CMR error HTTP {resp.status_code}: {resp.text[:200]}")

        entries = resp.json().get("feed", {}).get("entry", [])
        if not entries:
            break

        for entry in entries:
            parsed = parse_granule_title(entry.get("title", ""))
            if not parsed:
                log(f"  skipped unparsed title: {entry.get('title', '')[:80]}")
                continue
            key = f"{parsed['rgt']}_{parsed['date']}"
            if key in seen:
                continue
            seen.add(key)
            parsed["key"] = key
            parsed["select"] = True
            parsed["rings"] = []
            for poly in entry.get("polygons") or []:
                if isinstance(poly, list):
                    poly = poly[0] if poly else ""
                ring = parse_cmr_polygon(poly)
                parsed["rings"].extend(clip_ring_to_aoi(ring, bounds))
            found.append(parsed)

        if len(entries) < 200:
            break
        page += 1

    log(f"CMR: {len(found)} unique RGT/date passes")
    return found
