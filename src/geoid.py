"""Optional EGM2008 orthometric heights via PROJ. Never crash the download if missing."""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def build_transformer(log: Callable[[str], None] = print):
    try:
        import pyproj
        from pyproj import CRS, Transformer

        try:
            pyproj.network.set_network_enabled(True)
        except Exception:
            pass

        # EPSG:9518 = WGS84 geographic + EGM2008 height
        try:
            t = Transformer.from_crs("EPSG:4979", "EPSG:9518", always_xy=True)
            _, _, h_test = t.transform(73.04, 8.30, 0.0)
            n_test = 0.0 - h_test
            if np.isfinite(n_test) and abs(n_test) >= 1.0:
                log(f"EGM2008 grid ready (EPSG:9518), test N={n_test:.2f} m")
                return t
        except Exception as exc:
            log(f"EPSG:9518 unavailable ({exc}). Trying local gtx…")

        import os

        gtx = os.path.join(pyproj.datadir.get_data_dir(), "egm08_25.gtx")
        if not os.path.exists(gtx):
            log("egm08_25.gtx not installed — geoid skipped")
            return None
        t = Transformer.from_crs(
            "EPSG:4979",
            CRS.from_proj4("+proj=longlat +datum=WGS84 +geoidgrids=egm08_25.gtx +vunits=m"),
            always_xy=True,
        )
        _, _, h_test = t.transform(73.04, 8.30, 0.0)
        n_test = 0.0 - h_test
        if not np.isfinite(n_test) or abs(n_test) < 1.0:
            log("local gtx did not apply — geoid skipped")
            return None
        log(f"EGM2008 gtx ready, test N={n_test:.2f} m")
        return t
    except Exception as exc:
        log(f"Geoid unavailable: {exc}")
        return None


def apply_geoid(df: pd.DataFrame, transformer, log: Callable[[str], None] = print) -> pd.DataFrame:
    out = df.copy()
    if transformer is None:
        out["geoid_undulation"] = np.nan
        out["height_orthometric"] = np.nan
        return out
    try:
        _, _, h_ortho = transformer.transform(
            out["longitude"].to_numpy(),
            out["latitude"].to_numpy(),
            out["height"].to_numpy(),
        )
        undulation = out["height"].to_numpy() - h_ortho
        valid = np.isfinite(h_ortho) & np.isfinite(undulation)
        h_ortho = np.asarray(h_ortho, dtype=float)
        undulation = np.asarray(undulation, dtype=float)
        h_ortho[~valid] = np.nan
        undulation[~valid] = np.nan
        out["geoid_undulation"] = np.round(undulation, 4)
        out["height_orthometric"] = np.round(h_ortho, 4)
    except Exception as exc:
        log(f"  geoid apply failed: {exc}")
        out["geoid_undulation"] = np.nan
        out["height_orthometric"] = np.nan
    return out
