"""End-to-end download. Each beam is written to disk before the next request."""

from __future__ import annotations

import time
from typing import Callable

from shapely.geometry import box, mapping

from src.basemap import fetch_basemap
from src.cmr import search_granules
from src.export import SessionManager, write_csv, write_shapefile, zip_session
from src.geo import Bounds, area_km2, pad_bounds, validate_aoi
from src.geoid import apply_geoid, build_transformer
from src.openaltimetry import clean_beam_frames, fetch_track
from src.visualize import save_all_tracks_png, save_beam_png


def aoi_geojson(bounds: Bounds, extra: dict | None = None) -> dict:
    w, s, e, n = bounds
    props = {"area_km2": round(area_km2(bounds), 2)}
    if extra:
        props.update(extra)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(box(w, s, e, n)),
                "properties": props,
            }
        ],
    }


def run_download(
    *,
    product: str,
    bounds: Bounds,
    date_start: str,
    date_end: str,
    beams: list[str],
    min_confidence: int,
    apply_egm: bool,
    output_format: str,
    save_mode: str,
    sampling: bool,
    granules: list[dict] | None = None,
    make_plots: bool = False,
    make_zip: bool = False,
    log: Callable[[str], None] = print,
    progress: Callable[[float], None] | None = None,
) -> dict:
    err = validate_aoi(product, bounds, sampling)
    if err:
        raise ValueError(err)

    if not granules:
        log("Searching CMR…")
        granules = search_granules(product, bounds, date_start, date_end, log=log)
    if not granules:
        raise RuntimeError("No ICESat-2 tracks in this AOI / date range.")

    session = SessionManager(product)
    session.create_session()
    log(f"Session: {session.session_dir}")

    session.save_metadata(
        {
            "product": product,
            "date_start": date_start,
            "date_end": date_end,
            "beams": beams,
            "min_confidence": min_confidence,
            "apply_geoid": apply_egm,
            "output_format": output_format,
            "save_mode": save_mode,
            "sampling": sampling,
            "bbox": list(bounds),
            "area_km2": round(area_km2(bounds), 2),
            "data_source": "OpenAltimetry API + CMR",
            "total_tracks": len(granules),
        },
        aoi_geojson(bounds),
    )

    transformer = build_transformer(log=log) if apply_egm else None
    if apply_egm and transformer is None:
        log("Continuing without geoid columns (NaN).")

    all_beam_data: list[tuple] = []
    skipped: list[str] = []
    saved = 0
    n = len(granules)

    for i, g in enumerate(granules, start=1):
        rgt, cycle, date = g["rgt"], g["cycle"], g["date"]
        log(f"[{i}/{n}] RGT {rgt:04d}  cycle {cycle}  {date}")
        if progress:
            progress((i - 1) / n * 0.75)
        try:
            raw = fetch_track(
                product,
                date,
                rgt,
                bounds,
                beams,
                min_confidence=min_confidence,
                sampling=sampling,
                log=log,
            )
            parts = clean_beam_frames(raw, product, rgt, cycle, date, beams, min_confidence)
            if not parts:
                msg = f"RGT={rgt} {date} empty/filtered"
                skipped.append(msg)
                session.add_summary(
                    RGT=rgt, Cycle=cycle, Date=date, Beam="-",
                    Point_Count=0, Height_Min_m=None, Height_Max_m=None, Status="empty",
                )
                log(f"    {msg}")
                continue

            out_dir = session.out_dir(rgt, date, save_mode)
            for beam, df in parts:
                df = apply_geoid(df, transformer, log=log)
                csv_name = session.filename(rgt, date, cycle, beam, "csv")
                write_csv(df, out_dir / csv_name)
                if output_format == "shp":
                    write_shapefile(df, out_dir / session.filename(rgt, date, cycle, beam, "shp"))
                session.add_summary(
                    RGT=rgt,
                    Cycle=cycle,
                    Date=date,
                    Beam=beam,
                    Point_Count=len(df),
                    Height_Min_m=round(float(df["height"].min()), 2),
                    Height_Max_m=round(float(df["height"].max()), 2),
                    Status="saved",
                )
                all_beam_data.append((rgt, cycle, date, beam, df))
                saved += 1
                log(f"    saved {csv_name}  ({len(df):,} pts)")
        except Exception as exc:
            msg = f"RGT={rgt} {date} {exc}"
            skipped.append(msg)
            session.add_summary(
                RGT=rgt, Cycle=cycle, Date=date, Beam="-",
                Point_Count=0, Height_Min_m=None, Height_Max_m=None, Status=f"error:{str(exc)[:40]}",
            )
            log(f"    ERROR {exc}")
        time.sleep(0.4)

    if progress:
        progress(0.78)
    log("Building overview map…")
    bm_arr, bm_ext = fetch_basemap(pad_bounds(bounds, 0.04), log=log)

    for rgt, cycle, date, beam, df in all_beam_data:
        out_dir = session.out_dir(rgt, date, save_mode)
        png_name = f"{int(rgt):04d}_{date.replace('-', '')}_C{int(cycle):02d}_{beam}_viz.png"
        try:
            save_beam_png(df, rgt, cycle, date, beam, out_dir / png_name, bounds, bm_arr, bm_ext)
        except Exception as exc:
            log(f"    PNG failed {png_name}: {exc}")

    total_pts = int(sum(len(d[4]) for d in all_beam_data))
    overview = save_all_tracks_png(
        all_beam_data,
        bounds,
        product,
        date_start,
        date_end,
        total_pts,
        len(skipped),
        session.session_dir,
        bm_arr,
        bm_ext,
    )
    session.save_summary()

    zip_path = None
    try:
        zip_path = zip_session(session.session_dir)
        log(f"Zip: {zip_path}")
    except Exception as exc:
        log(f"Zip failed: {exc}")

    if progress:
        progress(1.0)

    best = None
    if all_beam_data:
        def _score(item):
            df = item[4]
            if "confidence" in df.columns:
                return int((df["confidence"] >= 3).sum())
            return len(df)

        best = max(all_beam_data, key=_score)

    return {
        "session_dir": session.session_dir,
        "zip_path": zip_path,
        "saved_files": saved,
        "points": total_pts,
        "skipped": skipped,
        "granules": len(granules),
        "overview": overview,
        "best": best,
        "all_beam_data": all_beam_data,
        "basemap": (bm_arr, bm_ext),
    }
