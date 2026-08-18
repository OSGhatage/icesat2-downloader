"""OpenAltimetry CSV download + column cleanup."""

from __future__ import annotations

import io
import re
import time
from typing import Callable

import pandas as pd

from src.config import CONF_NAMES, OA_ENDPOINTS
from src.geo import Bounds
from src.http import make_session

_EXACT = {
    "beam": "beam",
    "gt": "beam",
    "lat": "latitude",
    "latitude": "latitude",
    "lon": "longitude",
    "long": "longitude",
    "longitude": "longitude",
    "height": "height",
    "elevation": "height",
    "h": "height",
    "hmean": "height",
    "hli": "height",
    "htebestfit": "height",
    "conf": "confidence",
    "confidence": "confidence",
    "signalconfph": "confidence",
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in df.columns:
        key = _norm(str(col))
        if key in _EXACT:
            rename[col] = _EXACT[key]
            continue
        if key in {"hmean", "h_li", "h_te_best_fit"}:
            rename[col] = "height"
    out = df.rename(columns=rename)
    if "height" not in out.columns:
        for col in out.columns:
            key = _norm(str(col))
            if "height" in key or "elev" in key:
                out = out.rename(columns={col: "height"})
                break
    return out


def fetch_track(
    product: str,
    date: str,
    rgt: int,
    bounds: Bounds,
    beams: list[str],
    min_confidence: int = -2,
    sampling: bool = False,
    timeout: int = 120,
    retries: int = 1,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    url = OA_ENDPOINTS.get(product)
    if not url:
        raise ValueError(f"No OpenAltimetry endpoint for {product}")

    west, south, east, north = bounds
    params: list[tuple[str, str]] = [
        ("date", date),
        ("minx", str(west)),
        ("miny", str(south)),
        ("maxx", str(east)),
        ("maxy", str(north)),
        ("trackId", str(int(rgt))),
        ("client", "portal"),
        ("outputFormat", "csv"),
    ]
    for beam in beams:
        params.append(("beamNames", beam))
    if product == "ATL03":
        if sampling:
            params.append(("sampling", "true"))
        from src.beams import confidence_api_values

        names = confidence_api_values(min_confidence)
        if names:
            for name in names:
                params.append(("photonConfidence", name))

    last_err: Exception | None = None
    session = make_session()
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            resp = session.get(url, params=params, timeout=timeout)
            elapsed = time.time() - t0
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            text = resp.text.strip()
            if not text or text.startswith("{") or text.startswith("<"):
                # JSON error or HTML gateway page
                raise RuntimeError(text[:160] or "empty body")
            lines = text.splitlines()
            if len(lines) <= 1:
                return pd.DataFrame()
            df = pd.read_csv(io.StringIO(text))
            log(f"    OA {product} RGT {rgt:04d} {date}: {len(df):,} rows in {elapsed:.1f}s")
            return df
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
    raise RuntimeError(f"OpenAltimetry failed for RGT {rgt} {date}: {last_err}")


def clean_beam_frames(
    df: pd.DataFrame,
    product: str,
    rgt: int,
    cycle: int,
    date: str,
    beams: list[str],
    min_confidence: int,
) -> list[tuple[str, pd.DataFrame]]:
    if df is None or df.empty:
        return []

    df = normalize_columns(df)
    for col in ("latitude", "longitude", "height", "confidence"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if not {"latitude", "longitude", "height"}.issubset(df.columns):
        return []
    df = df.dropna(subset=["latitude", "longitude", "height"])
    if df.empty:
        return []

    if "beam" not in df.columns:
        df["beam"] = "unknown"
    df["beam"] = df["beam"].astype(str).str.lower()
    df = df[df["beam"].isin(beams)]

    if "confidence" not in df.columns:
        df["confidence"] = pd.NA
    else:
        df["confidence"] = df["confidence"].fillna(0).astype(int)
        if product == "ATL03" and min_confidence > -2:
            df = df[df["confidence"] >= min_confidence]

    if df.empty:
        return []

    df = df.copy()
    df["rgt"] = int(rgt)
    df["cycle"] = int(cycle)
    df["date"] = date
    df["confidence_label"] = df["confidence"].map(CONF_NAMES).fillna("Unknown")

    out: list[tuple[str, pd.DataFrame]] = []
    for beam in sorted(df["beam"].unique()):
        part = df[df["beam"] == beam].reset_index(drop=True)
        if not part.empty:
            out.append((beam, part))
    return out
