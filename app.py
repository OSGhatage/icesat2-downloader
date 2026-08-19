"""ICESat-2 Downloader — Streamlit UI."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from folium.plugins import Draw
from streamlit_folium import st_folium

load_dotenv()

from src.beams import resolve_beams
from src.cmr import search_granules
from src.config import ALL_BEAMS, APP_NAME, APP_VERSION, ICESAT2_START, SUPPORTED_PRODUCTS
from src.geo import area_km2, bounds_from_points, bounds_from_polygon, normalize_bounds, spans_deg, validate_aoi
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
        "aoi": None,
        "map_center": [20.0, 78.0],
        "map_zoom": 5,
        "granules": None,
        "result": None,
        "logs": [],
        "editor_rev": 0,
        "focus_key": "All",
        "result_file": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    if "date_start" not in st.session_state:
        st.session_state.date_start = max(date.fromisoformat(ICESAT2_START), today - timedelta(days=45))
    if "date_end" not in st.session_state:
        st.session_state.date_end = today - timedelta(days=5)


def log_line(msg: str) -> None:
    st.session_state.logs.append(str(msg))


def selected_granules() -> list[dict]:
    return [g for g in (st.session_state.granules or []) if g.get("select", True)]


def _sync_editor_into_granules() -> None:
    """data_editor lives below the map — apply its last state before we draw."""
    granules = st.session_state.granules
    if not granules:
        return
    key = f"granule_editor_{st.session_state.editor_rev}"
    edited = st.session_state.get(key)
    if edited is None or not hasattr(edited, "iloc"):
        return
    for i, g in enumerate(granules):
        if i < len(edited):
            g["select"] = bool(edited.iloc[i]["Get"])


_init_state()
_sync_editor_into_granules()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### {APP_NAME}")
    st.caption(f"v{APP_VERSION}")

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
        sampling = st.checkbox("Sample 1/1000  ·  larger AOI", value=False)

    beam_mode = st.radio(
        "Beams",
        ["all", "left", "right", "custom"],
        format_func=lambda v: {
            "all": "All 6",
            "left": "Left  ·  gtXl",
            "right": "Right  ·  gtXr",
            "custom": "Choose",
        }[v],
        horizontal=True,
    )
    custom_beams = st.multiselect(" ", ALL_BEAMS, default=ALL_BEAMS, label_visibility="collapsed") if beam_mode == "custom" else []
    beams = resolve_beams(beam_mode, custom_beams)

    apply_egm = st.toggle("EGM2008 heights", value=False)
    output_format = st.radio("Save as", ["csv", "shp"], format_func=lambda v: "CSV" if v == "csv" else "CSV + SHP", horizontal=True)
    save_mode = st.radio("Folders", ["date", "track"], format_func=lambda v: "By date" if v == "date" else "By track", horizontal=True)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
.hero {background: linear-gradient(135deg,#0b3d91 0%,#1a73e8 100%);
       color:white;padding:16px 20px;border-radius:12px;margin-bottom:12px;}
.hero h1 {font-size:1.45rem;margin:0 0 2px 0;font-weight:650;}
.hero p {margin:0;opacity:.9;font-size:.9rem;}
.okbox,.warnbox,.badbox {border-radius:8px;padding:8px 12px;font-size:.92rem;}
.okbox {background:#e8f5e9;border:1px solid #81c784;}
.warnbox {background:#fff8e1;border:1px solid #ffcc02;}
.badbox {background:#ffebee;border:1px solid #ef9a9a;}
.step {font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;
       color:#5f6b7a;font-weight:600;margin:4px 0 8px 0;}
div[data-testid="stSidebar"] {background:#f4f7fb;}
</style>
<div class="hero">
  <h1>ICESat-2 Data Downloader</h1>
  <p>Draw an area, pick tracks, download.</p>
</div>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Map builder
# ---------------------------------------------------------------------------
def build_map(aoi, granules, focus_key: str) -> folium.Map:
    if aoi:
        w, s, e, n = aoi
        center = [(s + n) / 2, (w + e) / 2]
        zoom = 10
    else:
        center = st.session_state.map_center
        zoom = int(st.session_state.map_zoom)

    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
    ).add_to(m)
    folium.TileLayer("CartoDB positron", name="Light").add_to(m)

    if aoi:
        w, s, e, n = aoi
        folium.Rectangle(
            bounds=[[s, w], [n, e]],
            color="#ff2d2d",
            weight=2,
            fill=True,
            fill_opacity=0.05,
            tooltip="AOI",
        ).add_to(m)

    if granules:
        for i, g in enumerate(granules):
            chosen = g.get("select", True)
            focused = focus_key not in (None, "All") and focus_key == g["key"]
            color = "#f5c400" if focused else TRACK_COLORS[i % len(TRACK_COLORS)]
            weight = 4 if focused else (2.5 if chosen else 1.2)
            opacity = 0.95 if focused or chosen else 0.35
            fill_op = 0.45 if focused else (0.28 if chosen else 0.08)
            for ring in g.get("rings") or []:
                folium.Polygon(
                    locations=ring,
                    color=color,
                    weight=weight,
                    opacity=opacity,
                    fill=True,
                    fill_color=color,
                    fill_opacity=fill_op,
                    tooltip=f"RGT {g['rgt']:04d}  ·  {g['date']}",
                ).add_to(m)
            if not g.get("rings") and aoi:
                w, s, e, n = aoi
                mid_lon = (w + e) / 2 + (i - len(granules) / 2) * 0.01
                folium.PolyLine(
                    [[s, mid_lon], [n, mid_lon]],
                    color=color,
                    weight=weight,
                    opacity=opacity,
                    tooltip=f"RGT {g['rgt']:04d}  ·  {g['date']}",
                ).add_to(m)

    if aoi:
        w, s, e, n = aoi
        m.fit_bounds([[s, w], [n, e]], padding=(24, 24))

    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "polygon": False,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "rectangle": True,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


# ---------------------------------------------------------------------------
# Step 1 — area
# ---------------------------------------------------------------------------
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
                st.session_state.granules = None
                st.session_state.result = None
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
            st.session_state.granules = None
            st.session_state.result = None
            st.rerun()

    aoi = st.session_state.aoi
    if not aoi:
        st.markdown('<div class="warnbox">Draw a rectangle on the map.</div>', unsafe_allow_html=True)
    else:
        w, s, e, n = aoi
        dx, dy = spans_deg(aoi)
        problem = validate_aoi(product, aoi, sampling)
        box_cls = "badbox" if problem else "okbox"
        extra = f"<br/>{problem}" if problem else ""
        st.markdown(
            f'<div class="{box_cls}">'
            f"<b>{dx:.2f}° × {dy:.2f}°</b>  ·  {area_km2(aoi):,.0f} km²"
            f"<br/>{s:.4f}, {w:.4f}  →  {n:.4f}, {e:.4f}"
            f"{extra}</div>",
            unsafe_allow_html=True,
        )

    b1, b2 = st.columns(2)
    with b1:
        search_clicked = st.button("Find tracks", type="primary", use_container_width=True, disabled=aoi is None)
    with b2:
        if st.button("Clear", use_container_width=True):
            st.session_state.aoi = None
            st.session_state.granules = None
            st.session_state.result = None
            st.session_state.logs = []
            st.session_state.focus_key = "All"
            st.rerun()

granules = st.session_state.granules
focus_key = st.session_state.focus_key
n_sel = len(selected_granules())
map_sig = f"{aoi}-{len(granules or [])}-{n_sel}-{focus_key}"

with map_col:
    fmap = build_map(st.session_state.aoi, granules, focus_key)
    map_out = st_folium(
        fmap,
        height=MAP_H,
        use_container_width=True,
        returned_objects=["last_active_drawing", "all_drawings"],
        key=f"main_map_{map_sig}",
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
        st.session_state.granules = None
        st.session_state.result = None
        st.rerun()


# ---------------------------------------------------------------------------
# Find tracks
# ---------------------------------------------------------------------------
if search_clicked:
    if date_start >= date_end:
        st.error("Start date must be before end date.")
    else:
        problem = validate_aoi(product, st.session_state.aoi, sampling)
        if problem:
            st.error(problem)
        else:
            with st.spinner("Searching…"):
                try:
                    found = search_granules(product, st.session_state.aoi, str(date_start), str(date_end), log=log_line)
                    st.session_state.granules = found
                    st.session_state.result = None
                    st.session_state.focus_key = "All"
                    st.session_state.editor_rev += 1
                    st.rerun()
                except Exception as exc:
                    st.session_state.granules = None
                    st.error(f"Search failed: {exc}")


# ---------------------------------------------------------------------------
# Step 2 — tracks
# ---------------------------------------------------------------------------
granules = st.session_state.granules
if granules is not None:
    st.markdown('<div class="step">2  ·  Tracks</div>', unsafe_allow_html=True)
    if not granules:
        st.warning("No tracks in this window. Widen the dates or the box.")
    else:
        st.caption("Check the files you want. Click a row name below the table to highlight it on the map.")
        tbl_col, act_col = st.columns([1.6, 1], gap="large")

        table = pd.DataFrame(
            [
                {
                    "Get": bool(g.get("select", True)),
                    "RGT": f"{int(g['rgt']):04d}",
                    "Date": g["date"],
                    "Cycle": int(g["cycle"]),
                }
                for g in granules
            ]
        )

        with tbl_col:
            edited = st.data_editor(
                table,
                column_config={
                    "Get": st.column_config.CheckboxColumn("Get", default=True),
                    "RGT": st.column_config.TextColumn("RGT", width="small"),
                    "Date": st.column_config.TextColumn("Date", width="medium"),
                    "Cycle": st.column_config.NumberColumn("Cycle", format="%d", width="small"),
                },
                disabled=["RGT", "Date", "Cycle"],
                hide_index=True,
                use_container_width=True,
                height=min(360, 80 + 36 * len(granules)),
                key=f"granule_editor_{st.session_state.editor_rev}",
            )
            for i, g in enumerate(st.session_state.granules):
                g["select"] = bool(edited.iloc[i]["Get"]) if i < len(edited) else True

        with act_col:
            n_sel = len(selected_granules())
            st.metric("Selected", f"{n_sel} / {len(granules)}")
            a1, a2 = st.columns(2)
            if a1.button("All", use_container_width=True):
                for g in st.session_state.granules:
                    g["select"] = True
                st.session_state.editor_rev += 1
                st.rerun()
            if a2.button("None", use_container_width=True):
                for g in st.session_state.granules:
                    g["select"] = False
                st.session_state.editor_rev += 1
                st.rerun()

            focus_labels = ["All"] + [f"RGT {g['rgt']:04d} · {g['date']}" for g in granules]
            focus_keys = ["All"] + [g["key"] for g in granules]
            current = st.session_state.focus_key
            idx = focus_keys.index(current) if current in focus_keys else 0
            picked = st.selectbox("Highlight on map", focus_labels, index=idx)
            st.session_state.focus_key = focus_keys[focus_labels.index(picked)]

            st.caption("Hover a strip on the map to see its RGT. Streamlit tables cannot highlight on hover, so use this list.")

        can_dl = bool(st.session_state.aoi and selected_granules())
        if st.button("Download selected", type="primary", disabled=not can_dl):
            st.session_state.logs = []
            progress = st.progress(0.0, text="Starting…")
            log_box = st.empty()

            def _log(msg: str) -> None:
                log_line(msg)
                log_box.code("\n".join(st.session_state.logs[-30:]), language="text")

            def _prog(frac: float) -> None:
                progress.progress(min(1.0, max(0.0, frac)), text=f"{int(frac * 100)}%")

            try:
                result = run_download(
                    product=product,
                    bounds=st.session_state.aoi,
                    date_start=str(date_start),
                    date_end=str(date_end),
                    beams=beams,
                    min_confidence=min_conf if is_atl03 else -2,
                    apply_egm=apply_egm,
                    output_format=output_format,
                    save_mode=save_mode,
                    sampling=sampling if is_atl03 else False,
                    granules=selected_granules(),
                    log=_log,
                    progress=_prog,
                )
                st.session_state.result = result
                st.session_state.result_file = None
                progress.progress(1.0, text="Done")
            except Exception as exc:
                st.session_state.result = None
                st.exception(exc)


# ---------------------------------------------------------------------------
# Step 3 — results
# ---------------------------------------------------------------------------
result = st.session_state.result
if result:
    st.markdown('<div class="step">3  ·  Results</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Files", result["saved_files"])
    m2.metric("Points", f"{result['points']:,}")
    m3.metric("Tracks", result["granules"])
    m4.metric("Skipped", len(result["skipped"]))

    zip_path = result.get("zip_path")
    if zip_path and Path(zip_path).exists():
        data = Path(zip_path).read_bytes()
        if len(data) < 80_000_000:
            st.download_button("Download ZIP", data=data, file_name=Path(zip_path).name, mime="application/zip")
        else:
            st.info(f"ZIP is {len(data)/1e6:.0f} MB — copy from `{zip_path}`.")

    if result["skipped"]:
        with st.expander(f"Skipped ({len(result['skipped'])})"):
            st.write("\n".join(result["skipped"]))

    files = result.get("all_beam_data") or []
    if files:
        labels = [f"RGT {int(r):04d}  ·  {bm}  ·  {ds}  ·  {len(df):,} pts" for r, c, ds, bm, df in files]
        current_label = st.session_state.result_file
        if current_label not in labels:
            current_label = labels[0]
            st.session_state.result_file = current_label
        chosen = st.selectbox("File", labels, index=labels.index(current_label))
        st.session_state.result_file = chosen
        item = files[labels.index(chosen)]
        rgt, cycle, date_s, beam, df = item

        view = bounds_from_points(df["longitude"], df["latitude"]) or st.session_state.aoi
        ov_col, pr_col = st.columns([1.15, 1], gap="large")

        with ov_col:
            st.caption("Selected file · cropped to its points")
            if view:
                vw, vs, ve, vn = view
                detail = folium.Map(location=[(vs + vn) / 2, (vw + ve) / 2], zoom_start=12, tiles=None, control_scale=True)
                folium.TileLayer(
                    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                    attr="Esri",
                ).add_to(detail)
                if st.session_state.aoi:
                    aw, as_, ae, an = st.session_state.aoi
                    folium.Rectangle([[as_, aw], [an, ae]], color="#ff2d2d", weight=2, fill=False).add_to(detail)
                for i, (rr, _c, _d, _b, other) in enumerate(files):
                    ordered = other.sort_values("latitude")
                    same = rr == rgt and _b == beam and _d == date_s
                    folium.PolyLine(
                        list(zip(ordered["latitude"], ordered["longitude"])),
                        color="#f5c400" if same else "#8899aa",
                        weight=4 if same else 1.5,
                        opacity=0.95 if same else 0.45,
                    ).add_to(detail)
                detail.fit_bounds([[vs, vw], [vn, ve]], padding=(18, 18))
                st_folium(detail, height=420, use_container_width=True, returned_objects=[], key=f"detail_{chosen}")

        with pr_col:
            st.caption("Elevation profile")
            chart_df = df[["latitude", "height"]].rename(columns={"latitude": "Latitude", "height": "Height_m"})
            st.scatter_chart(chart_df, x="Latitude", y="Height_m", height=420)

    with st.expander("Log"):
        st.code("\n".join(st.session_state.logs[-80:]), language="text")
        st.caption(f"{result['session_dir']}")
