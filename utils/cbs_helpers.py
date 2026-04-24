import json
import zipfile
from pathlib import Path
from typing import Optional

import cbsodata
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import streamlit as st


DEFAULT_TABLE_KWB = "85984NED"
DEFAULT_TABLE_SES = "86092NED"
DEFAULT_GPKG_URL = "https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2024_v2.zip"


def make_regios(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    for col in candidates:
        if col in df.columns:
            df = df.copy()
            df["RegioS"] = (
                df[col]
                .astype(str)
                .str.strip()
                .str.upper()
                .str.replace(r"\s+", "", regex=True)
            )
            return df
    raise KeyError(f"Geen regiocodekolom gevonden. Beschikbare kolommen: {df.columns.tolist()}")
    
def normalize_geo_regios(gdf: gpd.GeoDataFrame, niveau: str) -> gpd.GeoDataFrame:
    candidates_map = {
        "gemeente": ["RegioS", "statcode", "gemeentecode", "gm_code"],
        "wijk": ["RegioS", "statcode", "wijkcode", "wk_code"],
        "buurt": ["RegioS", "statcode", "buurtcode", "bu_code"],
    }

    candidates = candidates_map[niveau]
    lookup = {c.lower(): c for c in gdf.columns}

    found = None
    for c in candidates:
        if c.lower() in lookup:
            found = lookup[c.lower()]
            break

    if found is None:
        raise KeyError(
            f"Geen regiocodekolom gevonden voor niveau '{niveau}'. "
            f"Beschikbare geo-kolommen: {gdf.columns.tolist()}"
        )

    if found != "RegioS":
        gdf = gdf.rename(columns={found: "RegioS"})

    gdf["RegioS"] = (
        gdf["RegioS"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
    )

    return gdf


def detect_region_col(df: pd.DataFrame) -> Optional[str]:
    exact_candidates = [
        "RegioS",
        "Regios",
        "Regio",
        "WijkenEnBuurten",
        "WijkenEnBuurten_1",
        "Gebieden",
    ]

    for c in exact_candidates:
        if c in df.columns:
            return c

    for c in df.columns:
        cl = c.lower()
        if "regio" in cl or "wijk" in cl or "buurt" in cl or "gemeente" in cl:
            return c

    return None


def normalize_series(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    mn = s.min()
    mx = s.max()

    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        return pd.Series([0.5] * len(s), index=s.index)

    return (s - mn) / (mx - mn)


def find_first_column(columns, candidates):
    for cand in candidates:
        for c in columns:
            if cand in c.lower():
                return c
    return None


def get_numeric_columns(df: pd.DataFrame):
    numeric_cols = []
    for c in df.columns:
        if c in ["jaar_num"]:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            numeric_cols.append(c)
    return numeric_cols


@st.cache_data(show_spinner=True)
def load_kwb_data(table_kwb: str = DEFAULT_TABLE_KWB) -> pd.DataFrame:
    df = pd.DataFrame(cbsodata.get_data(table_kwb))

    df = make_regios(
        df,
        [
            "Codering_3",
            "RegiocodeGemeenteWijkBuurt_1",
            "WijkenEnBuurten",
            "WijkenEnBuurten_1",
            "RegioS",
        ]
    )
    if "Gemeentenaam_1" in df.columns:
        df["regio_naam"] = df["Gemeentenaam_1"].astype(str).str.strip()
    elif "Naam_1" in df.columns:
        df["regio_naam"] = df["Naam_1"].astype(str).str.strip()

    region_col = detect_region_col(df)
    if region_col is None:
        raise KeyError(f"Geen regiokolom gevonden in KWB-data. Kolommen: {df.columns.tolist()}")

    if region_col != "RegioS":
        df = df.rename(columns={region_col: "RegioS"})

    if "Perioden" in df.columns:
        df["Perioden"] = df["Perioden"].astype(str)

    df["RegioS"] = df["RegioS"].astype(str)

    df["niveau"] = np.select(
        [
            df["RegioS"].str.startswith("GM"),
            df["RegioS"].str.startswith("WK"),
            df["RegioS"].str.startswith("BU"),
        ],
        [
            "gemeente",
            "wijk",
            "buurt",
        ],
        default="overig",
    )
    st.write("Voorbeeld RegioS:", df["RegioS"].head(10).tolist())
    st.write("Verdeling niveau:", df["niveau"].value_counts(dropna=False))

    return df


@st.cache_data(show_spinner=True)
def load_ses_data(table_ses: str = DEFAULT_TABLE_SES):
    df = pd.DataFrame(cbsodata.get_data(table_ses))

    df = make_regios(
        df,
        [
            "RegiocodeGemeenteWijkBuurt_1",
            "Codering_3",
            "WijkenEnBuurten",
            "WijkenEnBuurten_1",
            "RegioS",
        ]
    )

    df["RegioS"] = df["RegioS"].astype(str)

    latest_year = None
    if "Perioden" in df.columns:
        df["Perioden"] = df["Perioden"].astype(str)
        df["jaar_num"] = df["Perioden"].str.extract(r"(\d{4})", expand=False).astype(float)
        if df["jaar_num"].notna().any():
            latest_year = int(df["jaar_num"].max())
            df = df[df["jaar_num"] == latest_year].copy()

    ses_score_col = find_first_column(df.columns, ["ses", "totaalscore"])
    spreiding_col = find_first_column(df.columns, ["spreiding"])

    keep = ["RegioS"]
    if ses_score_col:
        keep.append(ses_score_col)
    if spreiding_col:
        keep.append(spreiding_col)

    out = df[keep].copy()

    rename_map = {}
    if ses_score_col:
        rename_map[ses_score_col] = "SES_WOA_score"
    if spreiding_col:
        rename_map[spreiding_col] = "SES_WOA_spreiding"

    out = out.rename(columns=rename_map)

    return out, latest_year


@st.cache_data(show_spinner=True)
def download_and_extract_gpkg(
    gpkg_url: str = DEFAULT_GPKG_URL,
    data_dir: str = "data_cache",
):
    data_path = Path(data_dir)
    data_path.mkdir(exist_ok=True)

    zip_name = gpkg_url.split("/")[-1]
    zip_path = data_path / zip_name
    extract_dir = data_path / zip_name.replace(".zip", "")

    if not zip_path.exists():
        r = requests.get(gpkg_url, timeout=120)
        r.raise_for_status()
        zip_path.write_bytes(r.content)

    if not extract_dir.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

    gpkg_files = list(extract_dir.rglob("*.gpkg"))
    if not gpkg_files:
        raise FileNotFoundError("Geen .gpkg gevonden in de CBS-download.")

    return gpkg_files[0]


def pick_layer_name(gpkg_path: str, niveau: str):
    layers = gpd.list_layers(gpkg_path)["name"].tolist()
    niveau = niveau.lower()

    preferred = {
        "gemeente": ["gemeente", "gemeenten"],
        "wijk": ["wijk", "wijken"],
        "buurt": ["buurt", "buurten"],
    }.get(niveau, [niveau])

    for p in preferred:
        for layer in layers:
            if p in layer.lower():
                return layer

    return layers[0]


@st.cache_data(show_spinner=True)
def load_geometry(
    niveau: str,
    gpkg_url: str = DEFAULT_GPKG_URL,
    data_dir: str = "data_cache",
) -> gpd.GeoDataFrame:
    gpkg_path = download_and_extract_gpkg(gpkg_url=gpkg_url, data_dir=data_dir)
    layer = pick_layer_name(str(gpkg_path), niveau)
    gdf = gpd.read_file(gpkg_path, layer=layer)

    gdf = normalize_geo_regios(gdf, niveau)

    keep_cols = ["RegioS", "geometry"] + [
        c for c in gdf.columns if c not in ["RegioS", "geometry"]
    ]
    gdf = gdf[keep_cols].copy()
    gdf = gdf.to_crs(4326)

    return gdf
    
def simplify_geometry_for_web(
    gdf: gpd.GeoDataFrame,
    niveau: str,
    detail: str = "normaal",
) -> gpd.GeoDataFrame:
    """
    Houdt de hele kaart gevuld, maar maakt de geometrie lichter voor de browser.
    Alleen de lijnen worden simpeler; je verliest geen regio's.
    """

    tolerance_map = {
        "gemeente": {
            "globaal": 250,
            "normaal": 100,
            "detail": 25,
        },
        "wijk": {
            "globaal": 80,
            "normaal": 35,
            "detail": 10,
        },
        "buurt": {
            "globaal": 30,
            "normaal": 12,
            "detail": 4,
        },
    }

    tol = tolerance_map.get(niveau, {}).get(detail, 25)

    out = gdf.copy()
    out = out.to_crs(28992)
    out["geometry"] = out.geometry.simplify(tolerance=tol, preserve_topology=True)
    out = out.to_crs(4326)

    return out

def build_geojson(gdf: gpd.GeoDataFrame, fill_col: str, height_col: Optional[str] = None):
    gdf = gdf.copy()

    fill_norm = normalize_series(gdf[fill_col])
    gdf["fill_r"] = (255 * fill_norm).astype(int)
    gdf["fill_g"] = (80 + 100 * (1 - fill_norm)).astype(int)
    gdf["fill_b"] = (255 * (1 - fill_norm)).astype(int)
    gdf["fill_a"] = 150

    if height_col:
        height_norm = normalize_series(gdf[height_col])
        gdf["elevation"] = (500 + 9500 * height_norm).fillna(0).astype(float)
    else:
        gdf["elevation"] = 0.0

    return json.loads(gdf.to_json())


def build_centroids_df(gdf: gpd.GeoDataFrame, size_col: str):
    cent = gdf.copy()
    cent["geometry"] = cent.geometry.representative_point()
    cent["lon"] = cent.geometry.x
    cent["lat"] = cent.geometry.y

    size_norm = normalize_series(cent[size_col])
    cent["radius"] = (100 + 2200 * size_norm).fillna(0).astype(float)

    return pd.DataFrame(cent.drop(columns="geometry"))
