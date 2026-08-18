"""Shared constants. No secrets live here."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ICESat-2 Downloader"
APP_VERSION = "2.0.0"
USER_AGENT = f"ICESat2-Downloader/{APP_VERSION} (research; github-codespaces)"

# Official public APIs — no Earthdata login required for this scout path
CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
CMR_HEALTH_URL = "https://cmr.earthdata.nasa.gov/search/health"
OA_BASE = "https://openaltimetry.earthdatacloud.nasa.gov/data/api/icesat2"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

ICESAT2_START = "2018-10-14"

SUPPORTED_PRODUCTS = {
    "ATL03": "Photon-level heights (raw)",
    "ATL06": "Land ice elevation",
    "ATL07": "Sea ice elevation",
    "ATL08": "Vegetation / land surface",
    "ATL12": "Ocean surface height",
    "ATL13": "Inland water surface",
}

# OpenAltimetry published limits
OA_MAX_SPAN = {
    "ATL03": 1.0,  # degrees, unless sampling=True
    "DEFAULT": 5.0,
}

OA_ENDPOINTS = {
    "ATL03": f"{OA_BASE}/atl03",
    "ATL06": f"{OA_BASE}/atl06",
    "ATL07": f"{OA_BASE}/atl07",
    "ATL08": f"{OA_BASE}/atl08",
    "ATL12": f"{OA_BASE}/atl12",
    "ATL13": f"{OA_BASE}/atl13",
}

ALL_BEAMS = ["gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r"]
LEFT_BEAMS = ["gt1l", "gt2l", "gt3l"]
RIGHT_BEAMS = ["gt1r", "gt2r", "gt3r"]

# +X (forward) orientation only. Do not treat this as always-true.
BEAM_MODE_HELP = (
    "ICESat-2 strong/weak beams swap when the spacecraft flies backward (−X). "
    "Without the granule sc_orient flag (not in OpenAltimetry CSV), we cannot "
    "know which side is strong. Prefer named beams, or treat left/right as "
    "geometry, not strength."
)

CONF_COLORS = {
    -2: "#808080",
    -1: "#C0C0C0",
    0: "#FF0000",
    1: "#FF8C00",
    2: "#FFD700",
    3: "#32CD32",
    4: "#0000FF",
}
CONF_NAMES = {
    -2: "TEP",
    -1: "Not considered",
    0: "Noise",
    1: "Buffer",
    2: "Low",
    3: "Medium",
    4: "High",
}
CONF_API = {
    -2: "na",
    0: "noise",
    1: "buffer",
    2: "low",
    3: "medium",
    4: "high",
}

BEAM_COLORS = {
    "gt1l": "#d62728",
    "gt1r": "#ff9896",
    "gt2l": "#2ca02c",
    "gt2r": "#98df8a",
    "gt3l": "#1f77b4",
    "gt3r": "#aec7e8",
}

CSV_COLS = [
    "beam",
    "latitude",
    "longitude",
    "height",
    "confidence",
    "confidence_label",
    "geoid_undulation",
    "height_orthometric",
    "rgt",
    "cycle",
    "date",
]


def default_output_dir() -> Path:
    raw = os.environ.get("ICESAT2_OUT", "").strip()
    return Path(raw).expanduser() if raw else Path.cwd() / "data" / "sessions"
