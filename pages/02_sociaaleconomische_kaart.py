import io
import json
import zipfile
from pathlib import Path

import cbsodata
import geopandas as gpd
import numpy as np
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st


st.set_page_config(page_title="CBS sociaaleconomische kaart", layout="wide")

st.title("CBS sociaaleconomische kaart")
st.caption("KWB 2024 + SES-WOA 2023 + Wijk- en Buurtkaart 2024")

TABLE_KWB = "85984NED"
TABLE_SES = "86092NED"
GPKG_URL = "https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2024_v2.zip"
DATA_DIR = Path("data_cache")
DATA_DIR.mkdir(exist_ok=True)
ZIP_PATH = DATA_DIR / "WijkBuurtkaart_2024_v2.zip"
EXTRACT_DIR = DATA_DIR / "wijkbuurtkaart_2024"


# ----------------------------
# Helpers
# ----------------------------

def normalize_regios(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    lookup = {c.lower(): c for c in df.columns}

    found = None
    for c in candidates:
        if c.lower() in lookup:
            found = lookup[c.lower()]
            break

    if found is None:
        st.write("Kolommen:", df.columns.tolist())
        raise KeyError("Geen regiokolom gevonden.")

    if found != "RegioS":
        df = df.rename(columns={found: "RegioS"})

    df["RegioS"] = (
        df["RegioS"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    return df


def normalize_geo_regios(gdf: gpd.GeoDataFrame, niveau: str) -> gpd.GeoDataFrame:
    candidates_map = {
        "gemeente": ["RegioS", "statcode", "gemeentecode", "gemeentecode", "gm_code"],
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
        st.write("Geo-kolommen:", gdf.columns.tolist())
        raise KeyError(f"Geen regiocodekolom gevonden voor niveau: {niveau}")

    if found != "RegioS":
        gdf = gdf.rename(columns={found: "RegioS"})

    gdf["RegioS"] = (
        gdf["RegioS"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    return gdf

def detect_region_col(df: pd.DataFrame) -> str | None:
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
    cols_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        for c in columns:
            if cand in c.lower():
                return c
    return None


def get_dimension_table_name(table_id: str, keyword_candidates: list[str]) -> str | None:
    common = [
        "RegioS",
        "WijkenEnBuurten",
        "WijkenEnBuurten_1",
        "WijkenEnBuurten",
    ]
    for name in common:
        try:
            _ = cbsodata.get_data(table_id, name)
            return name
        except Exception:
            pass

    for name in keyword_candidates:
        try:
            _ = cbsodata.get_data(table_id, name)
            return name
        except Exception:
            pass

    return None


@st.cache_data(show_spinner=True)
def load_kwb_data():
    df = pd.DataFrame(cbsodata.get_data(TABLE_KWB))

    df = normalize_regios(
        df,
        ["RegioS", "Regios", "Regio", "WijkenEnBuurten", "WijkenEnBuurten_1", "Gebieden"]
    )

    region_col = detect_region_col(df)
    if region_col is None:
        st.write("Kolommen in KWB:", df.columns.tolist())
        raise KeyError("Geen regiokolom gevonden in KWB-data.")

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

    return df


@st.cache_data(show_spinner=True)
def load_ses_data():
    df = pd.DataFrame(cbsodata.get_data(TABLE_SES))

    df = normalize_regios(
        df,
        ["RegioS", "Regios", "Regio", "WijkenEnBuurten", "WijkenEnBuurten_1", "Gebieden"]
    )
    
    region_col = detect_region_col(df)
    if region_col is None:
        st.write("Kolommen in SES:", df.columns.tolist())
        raise KeyError("Geen regiokolom gevonden in SES-data.")

    if region_col != "RegioS":
        df = df.rename(columns={region_col: "RegioS"})

    df["RegioS"] = df["RegioS"].astype(str)

    if "Perioden" in df.columns:
        df["Perioden"] = df["Perioden"].astype(str)
        df["jaar_num"] = (
            df["Perioden"].str.extract(r"(\d{4})", expand=False).astype(float)
        )
        latest_year = int(df["jaar_num"].max())
        df = df[df["jaar_num"] == latest_year].copy()
    else:
        latest_year = None

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
def download_and_extract_gpkg():
    if not ZIP_PATH.exists():
        r = requests.get(GPKG_URL, timeout=120)
        r.raise_for_status()
        ZIP_PATH.write_bytes(r.content)

    if not EXTRACT_DIR.exists():
        EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ZIP_PATH, "r") as zf:
            zf.extractall(EXTRACT_DIR)

    gpkg_files = list(EXTRACT_DIR.rglob("*.gpkg"))
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


def pick_geo_code_column(gdf: gpd.GeoDataFrame, niveau: str):
    candidates = {
        "gemeente": ["gemeentecode", "gm_code", "code"],
        "wijk": ["wijkcode", "wk_code", "code"],
        "buurt": ["buurtcode", "bu_code", "code"],
    }.get(niveau, ["code"])

    for cand in candidates:
        for c in gdf.columns:
            if cand in c.lower():
                return c

    # fallback: eerste code-achtige kolom
    for c in gdf.columns:
        if "code" in c.lower():
            return c

    return None


@st.cache_data(show_spinner=True)
def load_geometry(niveau: str):
    gpkg_path = download_and_extract_gpkg()
    layer = pick_layer_name(str(gpkg_path), niveau)
    gdf = gpd.read_file(gpkg_path, layer=layer)

    gdf = normalize_geo_regios(gdf, niveau)

    # houd geometrie compact
    gdf = gdf[["RegioS", "geometry"] + [c for c in gdf.columns if c != "geometry" and c != "RegioS"]].copy()
    gdf = gdf.to_crs(4326)

    return gdf


def get_numeric_columns(df: pd.DataFrame):
    numeric_cols = []
    for c in df.columns:
        if c in ["jaar_num"]:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            numeric_cols.append(c)
    return numeric_cols


def build_geojson(gdf, fill_col, height_col=None):
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


def build_centroids_df(gdf, size_col):
    cent = gdf.copy()
    cent["geometry"] = cent.geometry.representative_point()
    cent["lon"] = cent.geometry.x
    cent["lat"] = cent.geometry.y

    size_norm = normalize_series(cent[size_col])
    cent["radius"] = (100 + 2200 * size_norm).fillna(0).astype(float)

    return pd.DataFrame(cent.drop(columns="geometry"))


# ----------------------------
# Load
# ----------------------------

with st.spinner("CBS-data laden..."):
    kwb = load_kwb_data()
    ses, ses_year = load_ses_data()

st.success(f"KWB geladen: {len(kwb):,} rijen | SES-WOA jaar: {ses_year if ses_year else 'onbekend'}")

# combineer
df = kwb.merge(ses, on="RegioS", how="left")

# ----------------------------
# Sidebar
# ----------------------------

st.sidebar.header("Kaartinstellingen")

niveau = st.sidebar.radio(
    "Regio-niveau",
    ["gemeente", "wijk", "buurt"],
    index=0,
)

df_level = df[df["niveau"] == niveau].copy()

if df_level.empty:
    st.error(f"Geen data gevonden voor niveau: {niveau}")
    st.stop()

numeric_cols = get_numeric_columns(df_level)
preferred_color = "SES_WOA_score" if "SES_WOA_score" in numeric_cols else numeric_cols[0]
preferred_height = "SES_WOA_spreiding" if "SES_WOA_spreiding" in numeric_cols else numeric_cols[min(1, len(numeric_cols)-1)]
preferred_size = numeric_cols[min(2, len(numeric_cols)-1)]

color_var = st.sidebar.selectbox("Kleur (vlak)", numeric_cols, index=numeric_cols.index(preferred_color) if preferred_color in numeric_cols else 0)
height_var = st.sidebar.selectbox("Hoogte / extrusie", ["Geen"] + numeric_cols, index=(["Geen"] + numeric_cols).index(preferred_height) if preferred_height in numeric_cols else 0)
size_var = st.sidebar.selectbox("Bubbels", ["Geen"] + numeric_cols, index=(["Geen"] + numeric_cols).index(preferred_size) if preferred_size in numeric_cols else 0)

show_table = st.sidebar.checkbox("Toon tabel", value=False)
limit_map = st.sidebar.checkbox("Beperk buurten voor performance", value=(niveau == "buurt"))
opacity = st.sidebar.slider("Opacity", 20, 255, 150, 5)
pitch = st.sidebar.slider("3D hoek", 0, 75, 35, 1)

if "regio_naam" in df_level.columns:
    search = st.sidebar.text_input("Zoek regio")
    if search:
        df_level = df_level[df_level["regio_naam"].fillna("").str.contains(search, case=False, na=False)].copy()

# ----------------------------
# Geometry
# ----------------------------

with st.spinner("Kaartgeometrie laden..."):
    gdf = load_geometry(niveau)

map_df = gdf.merge(df_level, on="RegioS", how="inner")

if limit_map and niveau == "buurt":
    # hou de app werkbaar op Streamlit Cloud
    map_df = map_df.sort_values(by=color_var, ascending=False).head(2500).copy()

if map_df.empty:
    st.error("Geen overlap tussen geometrie en data.")
    st.stop()

# tooltipvelden
tooltip_fields = ["RegioS"]
for extra in ["regio_naam", color_var]:
    if extra and extra in map_df.columns and extra not in tooltip_fields:
        tooltip_fields.append(extra)
if height_var != "Geen" and height_var in map_df.columns:
    tooltip_fields.append(height_var)
if size_var != "Geen" and size_var in map_df.columns:
    tooltip_fields.append(size_var)
if "SES_WOA_score" in map_df.columns and "SES_WOA_score" not in tooltip_fields:
    tooltip_fields.append("SES_WOA_score")

# kleur / hoogte
geojson = build_geojson(
    map_df,
    fill_col=color_var,
    height_col=None if height_var == "Geen" else height_var
)

# alpha overschrijven
for feature in geojson["features"]:
    feature["properties"]["fill_a"] = opacity

# bubbels
bubble_df = None
if size_var != "Geen" and size_var in map_df.columns:
    bubble_df = build_centroids_df(map_df, size_var)

# map center
center = map_df.geometry.unary_union.centroid
view_state = pdk.ViewState(
    latitude=float(center.y),
    longitude=float(center.x),
    zoom=6.2 if niveau == "gemeente" else 7.0 if niveau == "wijk" else 7.5,
    pitch=pitch,
)

polygon_layer = pdk.Layer(
    "GeoJsonLayer",
    data=geojson,
    pickable=True,
    stroked=True,
    filled=True,
    extruded=(height_var != "Geen"),
    wireframe=False,
    get_fill_color="[properties.fill_r, properties.fill_g, properties.fill_b, properties.fill_a]",
    get_line_color=[90, 90, 90, 120],
    get_line_width=40,
    get_elevation="properties.elevation",
)

layers = [polygon_layer]

if bubble_df is not None:
    bubble_layer = pdk.Layer(
        "ScatterplotLayer",
        data=bubble_df,
        pickable=True,
        get_position="[lon, lat]",
        get_radius="radius",
        get_fill_color=[30, 30, 30, 120],
        get_line_color=[255, 255, 255, 120],
        stroked=True,
    )
    layers.append(bubble_layer)

tooltip_html = "<br>".join([f"<b>{c}</b>: {{{c}}}" for c in tooltip_fields if c in map_df.columns])

st.subheader("Kaart")
st.pydeck_chart(
    pdk.Deck(
        map_style="light",
        initial_view_state=view_state,
        layers=layers,
        tooltip={"html": tooltip_html, "style": {"backgroundColor": "white", "color": "black"}},
    ),
    width="stretch",
)

# ----------------------------
# Correlatie / controles
# ----------------------------

st.subheader("Snel inzicht")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Regio-niveau", niveau)
c2.metric("Aantal gebieden", f"{len(map_df):,}")
c3.metric("Kleurvariabele", color_var)
c4.metric("SES-jaar", str(ses_year) if ses_year else "onbekend")

corr_candidates = [c for c in [color_var, height_var if height_var != "Geen" else None, size_var if size_var != "Geen" else None, "SES_WOA_score"] if c and c in map_df.columns]
corr_candidates = list(dict.fromkeys(corr_candidates))

if len(corr_candidates) >= 2:
    st.subheader("Correlatiematrix")
    corr_df = map_df[corr_candidates].apply(pd.to_numeric, errors="coerce")
    st.dataframe(corr_df.corr().round(3), width="stretch")

if show_table:
    st.subheader("Datatabel")
    preferred_cols = ["RegioS", "regio_naam", "SES_WOA_score", "SES_WOA_spreiding", color_var]
    if height_var != "Geen":
        preferred_cols.append(height_var)
    if size_var != "Geen":
        preferred_cols.append(size_var)

    preferred_cols = [c for c in preferred_cols if c in map_df.columns]
    others = [c for c in map_df.columns if c not in preferred_cols and c != "geometry"]

    st.dataframe(
        map_df[preferred_cols + others].drop(columns=[c for c in ["jaar_num", "niveau"] if c in map_df.columns], errors="ignore"),
        width="stretch",
        height=500,
    )
