"""ICESat-2 Downloader — Streamlit UI.

Run:
    streamlit run app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.beams import resolve_beams
from src.cmr import search_granules
from src.config import (
    ALL_BEAMS,
    APP_NAME,
    APP_VERSION,
    BEAM_MODE_HELP,
    CMR_HEALTH_URL,
    ICESAT2_START,
    OA_BASE,
    SUPPORTED_PRODUCTS,
)
from src.geo import area_km2, bounds_from_polygon, normalize_bounds, spans_deg, validate_aoi
from src.geocode import search_place
from src.http import configure, current_settings, ping
from src.pipeline import run_download

st.set_page_config(page_title=APP_NAME, page_icon="🛰️", layout="wide")

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
def _init_state() -> None:
    today = date.today()
    defaults = {
        "aoi": None,
        "map_center": [20.0, 78.0],
        "map_zoom": 5,
        "granules": None,
        "result": None,
        "logs": [],
        "place_name": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    if "date_start" not in st.session_state:
        st.session_state.date_start = max(date.fromisoformat(ICESAT2_START), today - timedelta(days=45))
    if "date_end" not in st.session_state:
        st.session_state.date_end = today - timedelta(days=5)


_init_state()


def log_line(msg: str) -> None:
    st.session_state.logs.append(str(msg))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### 🛰️ {APP_NAME}")
    st.caption(f"v{APP_VERSION} · OpenAltimetry + CMR · no login")

    product = st.selectbox(
        "Product",
        list(SUPPORTED_PRODUCTS.keys()),
        format_func=lambda k: f"{k} — {SUPPORTED_PRODUCTS[k]}",
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
            "ATL03 confidence (minimum)",
            options=[-2, 0, 2, 3, 4],
            value=3,
            format_func=lambda v: {
                -2: "All photons",
                0: "Noise+",
                2: "Low+",
                3: "Medium+",
                4: "High only",
            }[v],
        )
        sampling = st.checkbox(
            "Sample ATL03 (1/1000) — allows up to 5° AOI",
            value=False,
            help="OpenAltimetry otherwise limits ATL03 to 1° × 1°.",
        )
    else:
        st.caption("Confidence filter applies to ATL03 only.")

    st.markdown("**Beams**")
    beam_mode = st.radio(
        "Beam set",
        ["all", "left", "right", "custom"],
        format_func=lambda v: {
            "all": "All 6 beams",
            "left": "Left (gtXl)  · strong only in +X",
            "right": "Right (gtXr) · strong only in −X",
            "custom": "Custom list",
        }[v],
        label_visibility="collapsed",
    )
    custom_beams = []
    if beam_mode == "custom":
        custom_beams = st.multiselect("Named beams", ALL_BEAMS, default=ALL_BEAMS)
    beams = resolve_beams(beam_mode, custom_beams)
    st.caption(BEAM_MODE_HELP)

    apply_egm = st.toggle("EGM2008 orthometric height", value=False)
    output_format = st.radio("Files", ["csv", "shp"], format_func=lambda v: "CSV only" if v == "csv" else "CSV + Shapefile", horizontal=True)
    save_mode = st.radio("Folder layout", ["date", "track"], format_func=lambda v: "RGT / date" if v == "date" else "RGT / all", horizontal=True)

    with st.expander("Network (proxy only if you need it)"):
        st.write("Leave blank on Codespaces / home Wi-Fi.")
        proxy = st.text_input("Proxy URL", value="", type="password", placeholder="http://user:pass@host:8080")
        verify_ssl = st.checkbox("Verify SSL certificates", value=True)
        if st.button("Test NASA endpoints"):
            configure(proxy=proxy or None, verify_ssl=verify_ssl)
            ok1, m1 = ping(CMR_HEALTH_URL)
            ok2, m2 = ping(OA_BASE.replace("/api/icesat2", ""))
            st.write(f"CMR: {'OK' if ok1 else 'FAIL'} · {m1}")
            st.write(f"OpenAltimetry: {'OK' if ok2 else 'FAIL'} · {m2}")
            st.json(current_settings())

    configure(proxy=proxy or None, verify_ssl=verify_ssl)


# ---------------------------------------------------------------------------
# Header + how-to
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
.hero {background: linear-gradient(135deg,#0b3d91 0%,#1a73e8 100%);
       color:white;padding:18px 22px;border-radius:12px;margin-bottom:14px;}
.hero h1 {font-size:1.55rem;margin:0 0 4px 0;}
.hero p {margin:0;opacity:.92;font-size:.95rem;}
.okbox {background:#e8f5e9;border:1px solid #81c784;border-radius:8px;padding:10px 12px;}
.warnbox {background:#fff8e1;border:1px solid #ffcc02;border-radius:8px;padding:10px 12px;}
.badbox {background:#ffebee;border:1px solid #ef9a9a;border-radius:8px;padding:10px 12px;}
</style>
<div class="hero">
  <h1>ICESat-2 Data Downloader</h1>
  <p>Draw an AOI, search NASA CMR, download OpenAltimetry CSV / shapefile / maps.
     Works on public internet. Proxy is optional.</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.expander("How to use (Codespaces or laptop)", expanded=False):
    st.markdown(
        """
1. Search a place **or** type a bounding box **or** draw a rectangle on the map.
2. Keep the box within OpenAltimetry limits: **1° × 1°** for ATL03 (or enable sampling), **5° × 5°** for other products.
3. Click **Search tracks**, review the table, then **Download**.
4. Each beam is saved immediately (a crash does not wipe earlier files).
5. Download the session ZIP when it finishes.

This uses the public OpenAltimetry subset API, not NSIDC HDF5 granules.
Fine for scouting and teaching; use `earthaccess` / `icepyx` for papers.
"""
    )


# ---------------------------------------------------------------------------
# Place search + manual bbox
# ---------------------------------------------------------------------------
s1, s2 = st.columns([4, 1])
with s1:
    q = st.text_input("Find a place", placeholder='Lakshadweep   or   8.29, 73.04', label_visibility="collapsed")
with s2:
    do_search = st.button("Search place", use_container_width=True)

if do_search and q.strip():
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
        st.session_state.place_name = hit["name"]
        if hit["bounds"]:
            st.session_state.aoi = hit["bounds"]
            st.success(f"Using place bbox: {hit['name'][:90]}")
        else:
            st.info(f"Centered on {hit['name'][:90]} — draw a rectangle.")

with st.expander("Type a bounding box (always works if the map draw is flaky)"):
    aoi = st.session_state.aoi
    d1, d2, d3, d4 = st.columns(4)
    west_i = d1.number_input("West", value=float(aoi[0]) if aoi else 72.8, format="%.5f")
    south_i = d2.number_input("South", value=float(aoi[1]) if aoi else 8.2, format="%.5f")
    east_i = d3.number_input("East", value=float(aoi[2]) if aoi else 73.3, format="%.5f")
    north_i = d4.number_input("North", value=float(aoi[3]) if aoi else 8.6, format="%.5f")
    if st.button("Use typed box"):
        st.session_state.aoi = normalize_bounds(west_i, south_i, east_i, north_i)
        w, s, e, n = st.session_state.aoi
        st.session_state.map_center = [(s + n) / 2, (w + e) / 2]
        st.session_state.map_zoom = 10
        st.rerun()


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium

center = st.session_state.map_center
m = folium.Map(location=center, zoom_start=int(st.session_state.map_zoom), tiles=None, control_scale=True)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Satellite",
).add_to(m)
folium.TileLayer("OpenStreetMap", name="OSM").add_to(m)

if st.session_state.aoi:
    w, s, e, n = st.session_state.aoi
    folium.Rectangle(
        bounds=[[s, w], [n, e]],
        color="#ff2d2d",
        weight=3,
        fill=True,
        fill_opacity=0.08,
        tooltip="Current AOI",
    ).add_to(m)

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

map_out = st_folium(m, height=480, use_container_width=True, returned_objects=["last_active_drawing", "all_drawings"])

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


# ---------------------------------------------------------------------------
# AOI status
# ---------------------------------------------------------------------------
aoi = st.session_state.aoi
if not aoi:
    st.markdown('<div class="warnbox">Draw a <b>rectangle</b> on the map, search a place, or type a box.</div>', unsafe_allow_html=True)
else:
    w, s, e, n = aoi
    dx, dy = spans_deg(aoi)
    km2 = area_km2(aoi)
    problem = validate_aoi(product, aoi, sampling)
    box_cls = "badbox" if problem else "okbox"
    extra = f"<br/>⚠️ {problem}" if problem else ""
    st.markdown(
        f'<div class="{box_cls}">'
        f"<b>AOI</b> W {w:.5f} &nbsp; S {s:.5f} &nbsp; E {e:.5f} &nbsp; N {n:.5f}"
        f"<br/>{dx:.3f}° × {dy:.3f}° &nbsp;·&nbsp; ~{km2:,.1f} km² &nbsp;·&nbsp; beams {', '.join(beams)}"
        f"{extra}</div>",
        unsafe_allow_html=True,
    )

b1, b2, b3 = st.columns([1, 1, 2])
with b1:
    search_clicked = st.button("🔎 Search tracks", type="primary", use_container_width=True, disabled=aoi is None)
with b2:
    if st.button("🔄 Reset AOI", use_container_width=True):
        st.session_state.aoi = None
        st.session_state.granules = None
        st.session_state.result = None
        st.session_state.logs = []
        st.rerun()


# ---------------------------------------------------------------------------
# CMR search
# ---------------------------------------------------------------------------
if search_clicked:
    if date_start >= date_end:
        st.error("Start date must be before end date.")
    else:
        problem = validate_aoi(product, aoi, sampling)
        if problem:
            st.error(problem)
        else:
            with st.spinner("Querying NASA CMR…"):
                try:
                    st.session_state.granules = search_granules(
                        product, aoi, str(date_start), str(date_end), log=log_line
                    )
                    st.session_state.result = None
                except Exception as exc:
                    st.session_state.granules = None
                    st.error(f"CMR search failed: {exc}")

granules = st.session_state.granules
if granules is not None:
    if not granules:
        st.warning("No tracks in this window. Widen the dates or the box.")
    else:
        gdf = pd.DataFrame(granules)[["rgt", "cycle", "date", "title"]]
        st.success(f"Found {len(gdf)} track passes")
        st.dataframe(gdf, use_container_width=True, hide_index=True, height=min(360, 80 + 28 * len(gdf)))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
can_dl = bool(aoi and granules)
if st.button("⬇️ Download", type="primary", disabled=not can_dl):
    st.session_state.logs = []
    progress = st.progress(0.0, text="Starting…")
    log_box = st.empty()

    def _log(msg: str) -> None:
        log_line(msg)
        log_box.code("\n".join(st.session_state.logs[-40:]), language="text")

    def _prog(frac: float) -> None:
        progress.progress(min(1.0, max(0.0, frac)), text=f"{int(frac * 100)}%")

    try:
        result = run_download(
            product=product,
            bounds=aoi,
            date_start=str(date_start),
            date_end=str(date_end),
            beams=beams,
            min_confidence=min_conf if is_atl03 else -2,
            apply_egm=apply_egm,
            output_format=output_format,
            save_mode=save_mode,
            sampling=sampling if is_atl03 else False,
            granules=granules,
            log=_log,
            progress=_prog,
        )
        st.session_state.result = result
        progress.progress(1.0, text="Done")
    except Exception as exc:
        st.session_state.result = None
        st.exception(exc)


result = st.session_state.result
if result:
    st.markdown("### Results")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Files saved", result["saved_files"])
    m2.metric("Points", f"{result['points']:,}")
    m3.metric("Tracks searched", result["granules"])
    m4.metric("Skipped", len(result["skipped"]))
    st.caption(f"Folder: `{result['session_dir']}`")

    if result["skipped"]:
        with st.expander(f"Skipped / errors ({len(result['skipped'])})"):
            st.write("\n".join(result["skipped"]))

    zip_path = result.get("zip_path")
    if zip_path and Path(zip_path).exists():
        data = Path(zip_path).read_bytes()
        if len(data) < 80_000_000:
            st.download_button(
                "📦 Download session ZIP",
                data=data,
                file_name=Path(zip_path).name,
                mime="application/zip",
            )
        else:
            st.info(f"ZIP is {len(data)/1e6:.0f} MB — copy it from `{zip_path}` instead of the browser.")

    overview = result.get("overview")
    if overview and Path(overview).exists():
        st.image(str(overview), caption="All tracks in AOI", use_container_width=True)

    best = result.get("best")
    if best:
        rgt, cycle, date_s, beam, df = best
        st.markdown(f"**Preview** RGT {int(rgt):04d} · {beam} · {date_s} · {len(df):,} points")
        st.scatter_chart(df, x="latitude", y="height", height=280)

if st.session_state.logs and not result:
    with st.expander("Log"):
        st.code("\n".join(st.session_state.logs), language="text")
