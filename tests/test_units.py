from src.cmr import parse_granule_title
from src.geo import normalize_bounds, validate_aoi
from src.openaltimetry import normalize_columns
import pandas as pd


def test_parse_standard_title():
    p = parse_granule_title("ATL03_20181014005222_02350101_006_02.h5")
    assert p is not None
    assert p["product"] == "ATL03"
    assert p["rgt"] == 235
    assert p["cycle"] == 1
    assert p["date"] == "2018-10-14"


def test_parse_rejects_garbage():
    assert parse_granule_title("random_file.csv") is None


def test_atl03_limit():
    bounds = normalize_bounds(72.0, 8.0, 74.5, 9.0)  # 2.5 x 1
    assert validate_aoi("ATL03", bounds, sampling=False)
    assert validate_aoi("ATL03", bounds, sampling=True) is None
    small = normalize_bounds(72.8, 8.2, 73.3, 8.6)
    assert validate_aoi("ATL03", small, sampling=False) is None


def test_column_normalize():
    df = pd.DataFrame({"Lat": [1.0], "Lon": [2.0], "h_mean": [3.0], "conf": [4]})
    out = normalize_columns(df)
    assert {"latitude", "longitude", "height", "confidence"} <= set(out.columns)
