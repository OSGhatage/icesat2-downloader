# ICESat-2 Downloader

Browser app that lets you draw an area of interest, find ICESat-2 tracks, and download OpenAltimetry subsets as CSV, shapefile, and map PNGs.

Works on **normal internet** (home Wi-Fi, GitHub Codespaces). A corporate proxy is **optional** and only used if you set it.

No Earthdata password is stored in the code. The scout path (CMR + OpenAltimetry) does not need a login.

---

## Use it in GitHub Codespaces

1. Create a new GitHub repository (add a README so the `main` branch is not empty).
2. Upload this project folder, **or** from your laptop:

   ```bash
   git init
   git add .
   git commit -m "ICESat-2 downloader"
   git branch -M main
   git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
   git push -u origin main
   ```

3. On the repo page: **Code → Codespaces → Create codespace on main**.
4. Wait for the container to finish `pip install` (first boot is a few minutes).
5. In the Codespaces terminal:

   ```bash
   bash run.sh
   ```

6. When port **8501** appears, click **Open in Browser**.
7. Draw a small rectangle (see limits below) → **Search tracks** → **Download**.

Stop the Codespace when you are done so you do not burn free hours.

---

## Use it on a laptop

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
bash run.sh
```

Open http://localhost:8501

---

## OpenAltimetry limits (enforced in the UI)

| Product | Max AOI |
|---|---|
| ATL03 | **1° × 1°** (or 5° × 5° if you enable 1/1000 sampling) |
| ATL06 / 07 / 08 / 12 / 13 | **5° × 5°** |

Start with a small box and a few weeks of dates. ATL03 over a large area will be slow and can time out.

---

## What you get

Each run creates `data/sessions/ICESat2_<PRODUCT>_<timestamp>/`:

```
RRRR/YYYY-MM-DD/          # or RRRR/all/ if you pick "by track"
  *_ATL08.csv
  *_ATL08.shp + .prj + .dbf + .colnames.json
  *_viz.png
metadata/
  query_parameters.json
  aoi_boundary.geojson
  download_summary.csv
all_tracks_location_map.png
```

A ZIP of that folder is offered in the browser when it is not huge.

Beams are written **as they arrive**. If the kernel dies mid-run, earlier CSVs stay on disk.

---

## Optional lab proxy (NRSC / corporate)

Do **not** put passwords in the notebook or in git.

On the lab machine only:

```bash
export HTTPS_PROXY="http://USER:PASS@192.168.0.10:8080"
export HTTP_PROXY="$HTTPS_PROXY"
# only if the lab proxy breaks certificates
export ICESAT2_SSL_VERIFY=0
```

Or paste the proxy URL in the sidebar **Network** expander (it is not written to disk). On Codespaces and home Wi-Fi, leave it empty.

---

## What this is / is not

- **Is:** a scout tool. Draw a box, pull OpenAltimetry CSV, make maps.
- **Is not:** a replacement for NSIDC HDF5 via `earthaccess` / `icepyx`. Official granules have quality flags, `sc_orient`, and full photon groups.

**Beams:** left beams (`gt1l/gt2l/gt3l`) are strong only when the spacecraft flies **+X**. They swap in **−X**. OpenAltimetry CSV does not include `sc_orient`, so the app treats left/right as geometry, not as “always strong/weak”.

---

## Project layout

```
app.py                 Streamlit UI
src/cmr.py             NASA CMR search
src/openaltimetry.py   CSV download
src/geoid.py           optional EGM2008
src/export.py          CSV / shapefile / zip
src/visualize.py       PNG maps
src/http.py            proxy-optional sessions
```

---

## License / data

ICESat-2 data are provided by NASA / NSIDC. Cite the product DOI if you publish. This tool is a convenience wrapper around public APIs.
