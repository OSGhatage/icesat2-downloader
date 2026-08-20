"""Session folders, CSV, shapefile, zip. Files are written as each beam arrives."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config import CSV_COLS, default_output_dir


class SessionManager:
    def __init__(self, product: str, base_dir: Path | None = None):
        self.product = product
        self.base_dir = Path(base_dir) if base_dir else default_output_dir()
        self.session_id = ""
        self.session_dir = self.base_dir
        self.metadata_dir = self.base_dir
        self.summary_data: list[dict] = []

    def create_session(self) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.session_id = f"ICESat2_{self.product}_{ts}"
        self.session_dir = self.base_dir / self.session_id
        self.metadata_dir = self.session_dir / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        return self.session_dir

    def out_dir(self, rgt: int, date_str: str, save_mode: str) -> Path:
        if save_mode == "track":
            path = self.session_dir / f"{int(rgt):04d}" / "all"
        else:
            path = self.session_dir / f"{int(rgt):04d}" / date_str
        path.mkdir(parents=True, exist_ok=True)
        return path

    def filename(self, rgt, date_str, cycle, beam, ext: str) -> str:
        return (
            f"{int(rgt):04d}_{date_str.replace('-', '')}"
            f"_C{int(cycle):02d}_{beam}_{self.product}.{ext}"
        )

    def save_metadata(self, query_params: dict, aoi_geojson: dict) -> None:
        payload = {**query_params, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
        (self.metadata_dir / "query_parameters.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        (self.metadata_dir / "aoi_boundary.geojson").write_text(
            json.dumps(aoi_geojson, indent=2), encoding="utf-8"
        )

    def add_summary(self, **row) -> None:
        self.summary_data.append(row)

    def save_summary(self) -> pd.DataFrame | None:
        if not self.summary_data:
            return None
        df = pd.DataFrame(self.summary_data)
        df.to_csv(self.metadata_dir / "download_summary.csv", index=False)
        return df


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    cols = [c for c in CSV_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in cols and c != "index"]
    out = df[cols + extra].copy().dropna(axis=1, how="all")
    out.to_csv(path, index=False)
    return path


def write_shapefile(df: pd.DataFrame, path: Path) -> Path:
    import shapefile

    path = Path(path)
    stem = path.with_suffix("")
    field_map = {
        "beam": ("beam", "C", 8),
        "latitude": ("lat", "F", 12, 7),
        "longitude": ("lon", "F", 12, 7),
        "height": ("height", "F", 14, 4),
        "confidence": ("conf", "N", 4, 0),
        "confidence_label": ("conf_lbl", "C", 16),
        "geoid_undulation": ("geoid_N", "F", 12, 4),
        "height_orthometric": ("h_ortho", "F", 14, 4),
        "rgt": ("rgt", "N", 6, 0),
        "cycle": ("cycle", "N", 4, 0),
        "date": ("date", "C", 10),
    }

    writer = shapefile.Writer(str(stem), shapeType=shapefile.POINT)
    writer.autoBalance = 1
    used = []
    for col, spec in field_map.items():
        if col in df.columns:
            writer.field(*spec)
            used.append(col)

    for row in df.to_dict(orient="records"):
        writer.point(float(row["longitude"]), float(row["latitude"]))
        values = []
        for col in used:
            val = row.get(col)
            values.append(None if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val) else val)
        writer.record(*values)
    writer.close()

    prj = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
    )
    stem.with_suffix(".prj").write_text(prj, encoding="utf-8")

    rename = {c: field_map[c][0] for c in used}
    stem.with_suffix(".colnames.json").write_text(
        json.dumps(rename, indent=2), encoding="utf-8"
    )
    return stem.with_suffix(".shp")


def zip_session(session_dir: Path) -> Path:
    archive = Path(str(session_dir) + ".zip")
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(session_dir), "zip", root_dir=session_dir)
    return archive


def zip_selection(session_dir: Path, stems: list[str], dest: Path | None = None) -> Path:
    """Zip only files whose name starts with one of the given stems, plus metadata."""
    import zipfile

    session_dir = Path(session_dir)
    dest = Path(dest) if dest else session_dir.parent / f"{session_dir.name}_selected.zip"
    if dest.exists():
        dest.unlink()

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = session_dir / "metadata"
        if meta.exists():
            for p in meta.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(session_dir))
        for p in session_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.parent.name == "metadata":
                continue
            if any(p.name.startswith(stem) for stem in stems):
                zf.write(p, p.relative_to(session_dir))
    return dest
