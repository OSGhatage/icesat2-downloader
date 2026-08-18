"""Per-beam PNG and all-tracks overview. Default fonts — Times New Roman is not on Linux."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import box as sbox

from src.config import CONF_COLORS, CONF_NAMES
from src.geo import Bounds


def _draw_basemap(ax, bounds: Bounds, bm_arr, bm_ext) -> None:
    w, s, e, n = bounds
    cx, cy = (w + e) / 2, (s + n) / 2
    hs = max(e - w, n - s) / 2 * 1.15
    if bm_arr is not None and bm_ext is not None:
        ax.imshow(bm_arr, extent=bm_ext, aspect="equal", zorder=0, origin="upper", interpolation="bilinear")
    else:
        ax.set_facecolor("#e8e8e8")
        ax.grid(True, color="#cccccc", linewidth=0.5, alpha=0.7, zorder=0)
    ax.set_xlim(cx - hs, cx + hs)
    ax.set_ylim(cy - hs, cy + hs)
    ax.set_aspect("equal")


def _aoi_outline(ax, bounds: Bounds) -> None:
    w, s, e, n = bounds
    bx, by = sbox(w, s, e, n).exterior.xy
    ax.plot(bx, by, color="red", linewidth=2.0, label="AOI")
    ax.plot(bx, by, color="white", linewidth=0.8, linestyle="--", alpha=0.7)


def save_beam_png(df, rgt, cycle, date_s, beam, out_path: Path, bounds: Bounds, bm_arr=None, bm_ext=None) -> Path:
    fig = plt.figure(figsize=(16, 7))
    gs = fig.add_gridspec(1, 2, width_ratios=[4, 6], wspace=0.16)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

    _draw_basemap(ax1, bounds, bm_arr, bm_ext)
    if "confidence" in df.columns and df["confidence"].notna().any():
        for cv in sorted(df["confidence"].dropna().unique()):
            m = df["confidence"] == cv
            ax1.scatter(
                df.loc[m, "longitude"],
                df.loc[m, "latitude"],
                c=CONF_COLORS.get(int(cv), "#888888"),
                s=6,
                alpha=0.8,
                linewidths=0,
                label=f"{CONF_NAMES.get(int(cv), cv)} ({int(m.sum()):,})",
            )
    else:
        ax1.scatter(df["longitude"], df["latitude"], c="#1f77b4", s=6, alpha=0.8, linewidths=0, label=f"n={len(df):,}")
    _aoi_outline(ax1, bounds)
    ax1.set_title(f"Locations — RGT {int(rgt):04d} | {beam}")
    ax1.set_xlabel("Longitude (°)")
    ax1.set_ylabel("Latitude (°)")
    ax1.legend(fontsize=8, loc="upper right", framealpha=0.92)

    ycol = "height"
    if "confidence" in df.columns and df["confidence"].notna().any():
        for cv in sorted(df["confidence"].dropna().unique()):
            m = df["confidence"] == cv
            ax2.scatter(
                df.loc[m, "latitude"],
                df.loc[m, ycol],
                c=CONF_COLORS.get(int(cv), "#888888"),
                s=2,
                alpha=0.55,
                linewidths=0,
                label=f"{CONF_NAMES.get(int(cv), cv)} ({int(m.sum()):,})",
            )
    else:
        ax2.scatter(df["latitude"], df[ycol], c="#1f77b4", s=2, alpha=0.55, linewidths=0)
    med = float(np.nanmedian(df[ycol]))
    ax2.axhline(med, color="red", linestyle="--", linewidth=1.4, label=f"Median {med:.1f} m")
    ax2.set_title(f"Elevation — RGT {int(rgt):04d} | cycle {cycle} | {date_s}")
    ax2.set_xlabel("Latitude (°)")
    ax2.set_ylabel("Height (m, ellipsoid)")
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.92)
    ax2.grid(True, alpha=0.3)

    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return Path(out_path)


def save_all_tracks_png(all_beam_data, bounds: Bounds, product: str, date_start: str, date_end: str,
                        total_photons: int, skipped: int, session_dir: Path, bm_arr=None, bm_ext=None) -> Path | None:
    if not all_beam_data:
        return None
    out_path = Path(session_dir) / "all_tracks_location_map.png"
    fig, ax = plt.subplots(figsize=(11, 9))
    _draw_basemap(ax, bounds, bm_arr, bm_ext)

    unique_rgts = sorted({item[0] for item in all_beam_data})
    cmap = plt.colormaps.get_cmap("tab10")
    colors = {rgt: cmap(i % 10) for i, rgt in enumerate(unique_rgts)}
    seen = set()
    for rgt, _cycle, date_s, _beam, df in all_beam_data:
        label = f"RGT {int(rgt):04d} ({date_s})" if rgt not in seen else None
        ordered = df.sort_values("latitude")
        ax.plot(ordered["longitude"], ordered["latitude"], color=colors[rgt], linewidth=1.4, alpha=0.85, label=label)
        seen.add(rgt)

    _aoi_outline(ax, bounds)
    ax.set_title(
        f"ICESat-2 {product} tracks\n{date_start} → {date_end}  |  "
        f"{len(unique_rgts)} RGTs  |  {total_photons:,} points"
    )
    ax.set_xlabel("Longitude (°)")
    ax.set_ylabel("Latitude (°)")
    ax.legend(fontsize=8, loc="upper right", ncol=2, framealpha=0.92)
    ax.text(
        0.02,
        0.02,
        f"RGTs: {len(unique_rgts)}\nBeams: {len(all_beam_data)}\nPoints: {total_photons:,}\nSkipped: {skipped}",
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", alpha=0.88, edgecolor="gray"),
    )
    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path
