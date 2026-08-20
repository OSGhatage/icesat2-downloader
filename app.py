"""ICESat-2 Downloader — compose, inspect, then ZIP."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from folium.plugins import Draw
from streamlit_folium import st_folium

load_dotenv()

from src.beams import resolve_beams
from src.cmr import search_granules
from src.config import ALL_BEAMS, APP_NAME, APP_VERSION, BEAM_COLORS, ICESAT2_START, SUPPORTED_PRODUCTS
from src.export import zip_selection
from src.geo import (
    area_cap_km2,
    area_km2,
    bounds_from_points,
    bounds_from_polygon,
    normalize_bounds,
    spans_deg,
    validate_aoi,
    validate_dates,
)
from src.geocode import search_place
from src.http import configure
from src.pipeline import run_download

st.set_page_config(page_title=APP_NAME, page_icon="🛰️", layout="wide")
configure()

MAP_H = 620
TRACK_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#17becf",
]


def _init_state() -> None:
    today = date.today()
    defaults = {
        "mode": "compose",
        "aoi": None,
        "map_center": [20.0, 78.0],
        "map_zoom": 5,
        "granules": None,
        "result": None,
        "logs": [],
        "focus_key": None,
        "export": {},
        "view_beams": None,
        "plot_rev": 0,
        "zip_bytes": None,
        "zip_name": None,
        "zip_sig": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    if "date_start" not in st.session_state:
        st.session_state.date_start = max(date.fromisoformat(ICESAT2_START), today - timedelta(days=45))
    if "date_end" not in st.session_state:
        st.session_state.date_end = today - timedelta(days=5)


def reset_all() -> None:
    st.session_state.mode = "compose"
    st.session_state.aoi = None
    st.session_state.granules = None
    st.session_state.result = None
    st.session_state.logs = []
    st.session_state.focus_key = None
    st.session_state.export = {}
    st.session_state.view_beams = None
    st.session_state.zip_bytes = None
    st.session_state.zip_name = None
    st.session_state.zip_sig = None
    st.session_state.plot_rev += 1


def track_key(rgt, date_s) -> str:
    return f"{int(rgt)}_{date_s}"


def group_tracks(all_beam_data: list) -> dict:
    groups: dict[str, dict] = {}
    for rgt, cycle, date_s, beam, df in all_beam_data:
        key = track_key(rgt, date_s)
        slot = groups.setdefault(
            key,
            {"key": key, "rgt": int(rgt), "cycle": int(cycle), "date": date_s, "beams": {}},
        )
        slot["beams"][beam] = df
    return groups


def file_stem(rgt, date_s, cycle, beam, product: str) -> str:
    return f"{int(rgt):04d}_{date_s.replace('-', '')}_C{int(cycle):02d}_{beam}_{product}"


_init_state()


def log_line(msg: str) -> None:
    st.session_state.logs.append(str(msg))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
locked = st.session_state.mode == "inspect"

with st.sidebar:
    st.markdown(f"### {APP_NAME}")
    st.caption(f"v{APP_VERSION}")

    if locked:
        st.info("Parameters locked. Reset to start over.")
        if st.button("Reset", use_container_width=True):
            reset_all()
            st.rerun()
        res = st.session_state.result or {}
        aoi = st.session_state.aoi
        if aoi:
            st.caption(
                f"{st.session_state.get('locked_product', '')}  ·  "
                f"{st.session_state.get('locked_dates', '')}\n\n"
                f"{area_km2(aoi):,.0f} km²"
            )
    else:
        product = st.selectbox(
            "Product",
            list(SUPPORTED_PRODUCTS.keys()),
            format_func=lambda k: f"{k}  ·  {SUPPORTED_PRODUCTS[k]}",
        )
        is_atl03 = product == "ATL03"
        c1, c2 = st.columns(2)
        with c1:
            date_start = st.date_input("Start", key="date_start", min_value=date.fromisoformat(ICESAT2_START))
        with c2:
            date_end = st.date_input("End", key="date_end", min_value=date.fromisoformat(ICESAT2_START))

        sampling = False
        min_conf = -2
        if is_atl03:
            min_conf = st.select_slider(
                "Photon quality",
                options=[-2, 0, 2, 3, 4],
                value=3,
                format_func=lambda v: {-2: "All", 0: "Noise+", 2: "Low+", 3: "Medium+", 4: "High"}[v],
            )
            sampling = st.checkbox("Sample 1/1000", value=False)

        beam_mode = st.radio(
            "Beams to fetch",
            ["all", "left", "right", "custom"],
            format_func=lambda v: {"all": "All 6", "left": "Left", "right": "Right", "custom": "Choose"}[v],
            horizontal=True,
        )
        custom_beams = (
            st.multiselect(" ", ALL_BEAMS, default=ALL_BEAMS, label_visibility="collapsed")
            if beam_mode == "custom"
            else []
        )
        beams = resolve_beams(beam_mode, custom_beams)
        apply_egm = st.toggle("EGM2008 heights", value=False)
        output_format = st.radio(
            "Save as", ["csv", "shp"],
            format_func=lambda v: "CSV" if v == "csv" else "CSV + SHP",
            horizontal=True,
        )
        st.caption(f"Preview cap: {area_cap_km2(product):,.0f} km²")


# When locked, restore the values used for the fetch
if locked:
    product = st.session_state.get("locked_product", "ATL08")
    is_atl03 = product == "ATL03"
    date_start = st.session_state.date_start
    date_end = st.session_state.date_end
    sampling = st.session_state.get("locked_sampling", False)
    min_conf = st.session_state.get("locked_min_conf", -2)
    beams = st.session_state.get("locked_beams", list(ALL_BEAMS))
    apply_egm = st.session_state.get("locked_egm", False)
    output_format = st.session_state.get("locked_format", "csv")


st.markdown(
    """
<style>
.hero {background: linear-gradient(135deg,#0b3d91 0%,#1a73e8 100%);
       color:white;padding:16px 20px;border-radius:12px;margin-bottom:12px;}
.hero h1 {font-size:1.45rem;margin:0 0 2px 0;font-weight:650;}
.hero p {margin:0;opacity:.9;font-size:.9rem;}
.okbox,.warnbox,.badbox,.infobar {border-radius:8px;padding:8px 12px;font-size:.92rem;}
.okbox {background:#e8f5e9;border:1px solid #81c784;}
.warnbox {background:#fff8e1;border:1px solid #ffcc02;}
.badbox {background:#ffebee;border:1px solid #ef9a9a;}
.infobar {background:#eef3fb;border:1px solid #c5d4ea;display:flex;justify-content:space-between;gap:12px;}
.step {font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;
       color:#5f6b7a;font-weight:600;margin:4px 0 8px 0;}
div[data-testid="stSidebar"] {background:#f4f7fb;}
</style>
<div class="hero">
  <h1>ICESat-2 Data Downloader</h1>
  <p>Draw a small area, inspect tracks and beams, then download what you need.</p>
</div>
""",
    unsafe_allow_html=True,
)


# ===========================================================================
# MODE A — compose
# ===========================================================================
if st.session_state.mode == "compose":
    st.markdown('<div class="step">1  ·  Area</div>', unsafe_allow_html=True)
    map_col, tool_col = st.columns([1.35, 1], gap="large")

    with tool_col:
        q = st.text_input("Find a place", placeholder="Lakshadweep   or   8.29, 73.04")
        if st.button("Search", use_container_width=True) and q.strip():
            try:
                hit = search_place(q)
            except Exception as exc:
                st.error(f"Search failed: {exc}")
                hit = None
            if not hit:
                st.warning("No place found.")
            else:
                st.session_state.map_center = [hit["lat"], hit["lon"]]
                st.session_state.map_zoom = 10
                if hit["bounds"]:
                    st.session_state.aoi = hit["bounds"]
                st.rerun()

        with st.expander("Enter coordinates"):
            aoi_now = st.session_state.aoi
            d1, d2 = st.columns(2)
            west_i = d1.number_input("West", value=float(aoi_now[0]) if aoi_now else 72.8, format="%.5f")
            east_i = d2.number_input("East", value=float(aoi_now[2]) if aoi_now else 73.3, format="%.5f")
            south_i = d1.number_input("South", value=float(aoi_now[1]) if aoi_now else 8.2, format="%.5f")
            north_i = d2.number_input("North", value=float(aoi_now[3]) if aoi_now else 8.6, format="%.5f")
            if st.button("Use these coordinates", use_container_width=True):
                st.session_state.aoi = normalize_bounds(west_i, south_i, east_i, north_i)
                w, s, e, n = st.session_state.aoi
                st.session_state.map_center = [(s + n) / 2, (w + e) / 2]
                st.session_state.map_zoom = 10
                st.rerun()

        aoi = st.session_state.aoi
        if not aoi:
            st.markdown('<div class="warnbox">Draw a rectangle on the map.</div>', unsafe_allow_html=True)
        else:
            w, s, e, n = aoi
            dx, dy = spans_deg(aoi)
            problem = validate_aoi(product, aoi, sampling) or validate_dates(date_start, date_end)
            box_cls = "badbox" if problem else "okbox"
            extra = f"<br/>{problem}" if problem else ""
            st.markdown(
                f'<div class="{box_cls}">'
                f"<b>{dx:.2f}° × {dy:.2f}°</b>  ·  {area_km2(aoi):,.0f} km²"
                f"<br/>{s:.4f}, {w:.4f}  →  {n:.4f}, {e:.4f}"
                f"{extra}</div>",
                unsafe_allow_html=True,
            )

        get_clicked = st.button(
            "Get data",
            type="primary",
            use_container_width=True,
            disabled=aoi is None,
        )
        if st.button("Clear", use_container_width=True):
            reset_all()
            st.rerun()

    with map_col:
        aoi = st.session_state.aoi
        if aoi:
            w, s, e, n = aoi
            center = [(s + n) / 2, (w + e) / 2]
        else:
            center = st.session_state.map_center
        fmap = folium.Map(location=center, zoom_start=int(st.session_state.map_zoom), tiles=None, control_scale=True)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Satellite",
        ).add_to(fmap)
        folium.TileLayer("CartoDB positron", name="Light").add_to(fmap)
        if aoi:
            w, s, e, n = aoi
            folium.Rectangle([[s, w], [n, e]], color="#ff2d2d", weight=2, fill=True, fill_opacity=0.05, tooltip="AOI").add_to(fmap)
            fmap.fit_bounds([[s, w], [n, e]], padding=(24, 24))
        Draw(
            export=False,
            draw_options={
                "polyline": False, "polygon": False, "circle": False,
                "circlemarker": False, "marker": False, "rectangle": True,
            },
            edit_options={"edit": True, "remove": True},
        ).add_to(fmap)
        folium.LayerControl(collapsed=True).add_to(fmap)
        map_out = st_folium(
            fmap, height=MAP_H, use_container_width=True,
            returned_objects=["last_active_drawing", "all_drawings"],
            key="compose_map",
        )

    drawing = None
    if map_out:
        drawing = map_out.get("last_active_drawing") or None
        if not drawing and map_out.get("all_drawings"):
            drawing = map_out["all_drawings"][-1]
    if drawing and drawing.get("geometry", {}).get("type") == "Polygon":
        nb = bounds_from_polygon(drawing["geometry"]["coordinates"])
        if nb and nb != st.session_state.aoi:
            st.session_state.aoi = nb
            w, s, e, n = nb
            st.session_state.map_center = [(s + n) / 2, (w + e) / 2]
            st.rerun()

    if get_clicked:
        aoi = st.session_state.aoi
        err = (validate_dates(date_start, date_end) if aoi else "Draw an AOI first.") or validate_aoi(product, aoi, sampling)
        if err:
            st.error(err)
        else:
            st.session_state.logs = []
            progress = st.progress(0.0, text="Searching…")
            log_box = st.empty()

            def _log(msg: str) -> None:
                log_line(msg)
                log_box.code("\n".join(st.session_state.logs[-24:]), language="text")

            def _prog(frac: float) -> None:
                progress.progress(min(1.0, max(0.0, frac)), text=f"{int(frac * 100)}%")

            try:
                found = search_granules(product, aoi, str(date_start), str(date_end), log=_log)
                if not found:
                    st.warning("No tracks in this window.")
                else:
                    result = run_download(
                        product=product,
                        bounds=aoi,
                        date_start=str(date_start),
                        date_end=str(date_end),
                        beams=beams,
                        min_confidence=min_conf if is_atl03 else -2,
                        apply_egm=apply_egm,
                        output_format=output_format,
                        save_mode="date",
                        sampling=sampling if is_atl03 else False,
                        granules=found,
                        make_plots=False,
                        make_zip=False,
                        log=_log,
                        progress=_prog,
                    )
                    if not result.get("all_beam_data"):
                        st.error("Tracks were found but no points came back. Try another box or dates.")
                    else:
                        st.session_state.result = result
                        st.session_state.granules = found
                        groups = group_tracks(result["all_beam_data"])
                        export = {}
                        for key, g in groups.items():
                            export[key] = {
                                "include": True,
                                "beams": {b: True for b in g["beams"]},
                            }
                        st.session_state.export = export
                        st.session_state.focus_key = next(iter(groups))
                        st.session_state.view_beams = None
                        st.session_state.locked_product = product
                        st.session_state.locked_dates = f"{date_start} → {date_end}"
                        st.session_state.locked_sampling = sampling
                        st.session_state.locked_min_conf = min_conf
                        st.session_state.locked_beams = list(beams)
                        st.session_state.locked_egm = apply_egm
                        st.session_state.locked_format = output_format
                        st.session_state.mode = "inspect"
                        st.rerun()
            except Exception as exc:
                st.exception(exc)


# ===========================================================================
# MODE B — inspect
# ===========================================================================
else:
    result = st.session_state.result
    aoi = st.session_state.aoi
    groups = group_tracks(result["all_beam_data"]) if result else {}
    keys = list(groups)
    if not keys:
        st.warning("No data in this session.")
        if st.button("Reset"):
            reset_all()
            st.rerun()
        st.stop()

    if st.session_state.focus_key not in groups:
        st.session_state.focus_key = keys[0]
    focus = groups[st.session_state.focus_key]
    available_beams = sorted(focus["beams"])
    if st.session_state.view_beams is None:
        st.session_state.view_beams = list(available_beams)

    w, s, e, n = aoi if aoi else (0, 0, 1, 1)
    top_l, top_r = st.columns([4, 1])
    with top_l:
        st.markdown(
            f'<div class="infobar"><span>'
            f"<b>{product}</b>  ·  {st.session_state.get('locked_dates', '')}  ·  "
            f"{area_km2(aoi):,.0f} km²  ·  {len(groups)} tracks  ·  {result['points']:,} points"
            f"</span></div>",
            unsafe_allow_html=True,
        )
    with top_r:
        if st.button("Reset", use_container_width=True):
            reset_all()
            st.rerun()

    st.markdown('<div class="step">2  ·  Inspect</div>', unsafe_allow_html=True)
    list_col, view_col = st.columns([0.72, 2.1], gap="large")

    with list_col:
        st.caption("Highlight")
        labels = [f"RGT {groups[k]['rgt']:04d}  ·  {groups[k]['date']}" for k in keys]
        current_idx = keys.index(st.session_state.focus_key)
        picked = st.radio("Tracks", labels, index=current_idx, label_visibility="collapsed")
        new_key = keys[labels.index(picked)]
        if new_key != st.session_state.focus_key:
            st.session_state.focus_key = new_key
            st.session_state.view_beams = None
            st.session_state.plot_rev += 1
            st.rerun()

        st.caption("Beams on plot")
        view = st.multiselect(
            "Beams",
            available_beams,
            default=[b for b in (st.session_state.view_beams or available_beams) if b in available_beams],
            label_visibility="collapsed",
        )
        st.session_state.view_beams = view or list(available_beams)

    with view_col:
        map_c, plot_c = st.columns(2, gap="medium")
        view_set = set(st.session_state.view_beams or available_beams)

        with map_c:
            inspect = folium.Map(location=[(s + n) / 2, (w + e) / 2], zoom_start=11, tiles=None, control_scale=True)
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                attr="Esri",
            ).add_to(inspect)
            if aoi:
                folium.Rectangle([[s, w], [n, e]], color="#ff2d2d", weight=2, fill=False).add_to(inspect)

            for i, key in enumerate(keys):
                g = groups[key]
                active = key == st.session_state.focus_key
                beams_to_draw = (view_set if active else g["beams"].keys())
                for beam in beams_to_draw:
                    df = g["beams"][beam]
                    if df.empty:
                        continue
                    ordered = df.sort_values("latitude")
                    color = BEAM_COLORS.get(beam, "#f5c400") if active else "#8a97a6"
                    folium.PolyLine(
                        list(zip(ordered["latitude"], ordered["longitude"])),
                        color=color,
                        weight=4 if active else 1.6,
                        opacity=0.95 if active else 0.4,
                        tooltip=f"RGT {g['rgt']:04d}  {beam}  {g['date']}",
                    ).add_to(inspect)

            # crop to focused file
            focus_lons, focus_lats = [], []
            for beam, df in focus["beams"].items():
                if beam in view_set:
                    focus_lons.extend(df["longitude"].tolist())
                    focus_lats.extend(df["latitude"].tolist())
            view_b = bounds_from_points(focus_lons, focus_lats) if focus_lons else aoi
            if view_b:
                vw, vs, ve, vn = view_b
                inspect.fit_bounds([[vs, vw], [vn, ve]], padding=(20, 20))
            elif aoi:
                inspect.fit_bounds([[s, w], [n, e]], padding=(20, 20))
            st_folium(
                inspect, height=420, use_container_width=True, returned_objects=[],
                key=f"inspect_map_{st.session_state.focus_key}_{','.join(sorted(view_set))}",
            )

        with plot_c:
            fig = go.Figure()
            lats, hs = [], []
            for beam in available_beams:
                if beam not in view_set:
                    continue
                df = focus["beams"][beam]
                fig.add_trace(
                    go.Scattergl(
                        x=df["latitude"],
                        y=df["height"],
                        mode="markers",
                        name=beam,
                        marker=dict(size=4, color=BEAM_COLORS.get(beam, "#1f77b4"), opacity=0.75),
                    )
                )
                lats.extend(df["latitude"].tolist())
                hs.extend(df["height"].tolist())
            if lats:
                xpad = max((max(lats) - min(lats)) * 0.06, 0.002)
                ypad = max((max(hs) - min(hs)) * 0.08, 0.5)
                fig.update_xaxes(range=[min(lats) - xpad, max(lats) + xpad], title="Latitude")
                fig.update_yaxes(range=[min(hs) - ypad, max(hs) + ypad], title="Height (m)")
            fig.update_layout(
                height=420,
                margin=dict(l=50, r=16, t=28, b=48),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                title=f"RGT {focus['rgt']:04d}  ·  {focus['date']}",
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                key=f"plot_{st.session_state.focus_key}_{st.session_state.plot_rev}",
                config={"scrollZoom": True, "displaylogo": False},
            )
            if st.button("Reset plot", key="reset_plot"):
                st.session_state.plot_rev += 1
                st.rerun()

    st.markdown('<div class="step">3  ·  Download</div>', unsafe_allow_html=True)
    a1, a2, a3 = st.columns([1, 1, 3])
    if a1.button("Select all", use_container_width=True):
        for key, g in groups.items():
            st.session_state.export[key] = {"include": True, "beams": {b: True for b in g["beams"]}}
        st.rerun()
    if a2.button("Select none", use_container_width=True):
        for key, g in groups.items():
            st.session_state.export[key] = {"include": False, "beams": {b: False for b in g["beams"]}}
        st.rerun()

    for key, g in groups.items():
        slot = st.session_state.export.setdefault(
            key, {"include": True, "beams": {b: True for b in g["beams"]}}
        )
        cols = st.columns([1.1, 1.3, 1.2] + [0.7] * max(len(g["beams"]), 1))
        slot["include"] = cols[0].checkbox(
            f"RGT {g['rgt']:04d}",
            value=bool(slot.get("include", True)),
            key=f"inc_{key}",
        )
        cols[1].markdown(f"<div style='padding-top:8px'>{g['date']}</div>", unsafe_allow_html=True)
        cols[2].markdown(f"<div style='padding-top:8px'>cycle {g['cycle']}</div>", unsafe_allow_html=True)
        for i, beam in enumerate(sorted(g["beams"])):
            slot["beams"][beam] = cols[3 + i].checkbox(
                beam,
                value=bool(slot["beams"].get(beam, True)),
                key=f"bm_{key}_{beam}",
                disabled=not slot["include"],
            )

    stems = []
    n_files = 0
    for key, g in groups.items():
        slot = st.session_state.export.get(key, {})
        if not slot.get("include"):
            continue
        for beam, on in slot.get("beams", {}).items():
            if on and beam in g["beams"]:
                stems.append(file_stem(g["rgt"], g["date"], g["cycle"], beam, product))
                n_files += 1

    st.caption(f"{n_files} file{'s' if n_files != 1 else ''} selected")

    zip_sig = tuple(stems)
    if n_files and st.session_state.get("zip_sig") != zip_sig:
        try:
            zpath = zip_selection(Path(result["session_dir"]), stems)
            st.session_state.zip_bytes = zpath.read_bytes()
            st.session_state.zip_name = zpath.name
            st.session_state.zip_sig = zip_sig
        except Exception as exc:
            st.session_state.zip_bytes = None
            st.error(f"ZIP failed: {exc}")
    if n_files == 0:
        st.session_state.zip_bytes = None

    if st.session_state.zip_bytes:
        st.download_button(
            "Download ZIP",
            data=st.session_state.zip_bytes,
            file_name=st.session_state.zip_name or "icesat2_selected.zip",
            mime="application/zip",
            type="primary",
        )

    with st.expander("Log"):
        st.code("\n".join(st.session_state.logs[-80:]), language="text")
        if result:
            st.caption(str(result.get("session_dir", "")))
