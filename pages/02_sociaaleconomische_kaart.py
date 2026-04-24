import pandas as pd
import pydeck as pdk
import streamlit as st

from utils.cbs_helpers import (
    build_centroids_df,
    build_geojson,
    get_numeric_columns,
    load_geometry,
    load_kwb_data,
    load_ses_data,
)


st.set_page_config(page_title="CBS sociaaleconomische kaart", layout="wide")

st.title("CBS sociaaleconomische kaart")
st.caption("KWB 2024 + SES-WOA 2023 + Wijk- en Buurtkaart 2024")

with st.spinner("CBS-data laden..."):
    kwb = load_kwb_data()
    ses, ses_year = load_ses_data()

st.success(f"KWB geladen: {len(kwb):,} rijen | SES-WOA jaar: {ses_year if ses_year else 'onbekend'}")

df = kwb.merge(ses, on="RegioS", how="left")

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

if not numeric_cols:
    st.error("Geen numerieke kolommen beschikbaar voor kaartweergave.")
    st.stop()

preferred_color = "SES_WOA_score" if "SES_WOA_score" in numeric_cols else numeric_cols[0]
preferred_height = "SES_WOA_spreiding" if "SES_WOA_spreiding" in numeric_cols else numeric_cols[min(1, len(numeric_cols) - 1)]
preferred_size = numeric_cols[min(2, len(numeric_cols) - 1)]

color_var = st.sidebar.selectbox(
    "Kleur (vlak)",
    numeric_cols,
    index=numeric_cols.index(preferred_color) if preferred_color in numeric_cols else 0,
)

height_options = ["Geen"] + numeric_cols
size_options = ["Geen"] + numeric_cols

height_var = st.sidebar.selectbox(
    "Hoogte / extrusie",
    height_options,
    index=height_options.index(preferred_height) if preferred_height in height_options else 0,
)

size_var = st.sidebar.selectbox(
    "Bubbels",
    size_options,
    index=size_options.index(preferred_size) if preferred_size in size_options else 0,
)

show_table = st.sidebar.checkbox("Toon tabel", value=False)
limit_map = st.sidebar.checkbox("Beperk buurten voor performance", value=(niveau == "buurt"))
opacity = st.sidebar.slider("Opacity", 20, 255, 150, 5)
pitch = st.sidebar.slider("3D hoek", 0, 75, 35, 1)

if "regio_naam" in df_level.columns:
    search = st.sidebar.text_input("Zoek regio")
    if search:
        df_level = df_level[
            df_level["regio_naam"].fillna("").str.contains(search, case=False, na=False)
        ].copy()

with st.spinner("Kaartgeometrie laden..."):
    gdf = load_geometry(niveau)

map_df = gdf.merge(df_level, on="RegioS", how="inner")

if limit_map and niveau == "buurt":
    map_df = map_df.sort_values(by=color_var, ascending=False).head(2500).copy()

if map_df.empty:
    st.error("Geen overlap tussen geometrie en data.")
    st.stop()

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

geojson = build_geojson(
    map_df,
    fill_col=color_var,
    height_col=None if height_var == "Geen" else height_var,
)

for feature in geojson["features"]:
    feature["properties"]["fill_a"] = opacity

bubble_df = None
if size_var != "Geen" and size_var in map_df.columns:
    bubble_df = build_centroids_df(map_df, size_var)

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

tooltip_html = "<br>".join(
    [f"<b>{c}</b>: {{{c}}}" for c in tooltip_fields if c in map_df.columns]
)

st.subheader("Kaart")
st.pydeck_chart(
    pdk.Deck(
        map_style="light",
        initial_view_state=view_state,
        layers=layers,
        tooltip={
            "html": tooltip_html,
            "style": {"backgroundColor": "white", "color": "black"},
        },
    ),
    width="stretch",
)

st.subheader("Snel inzicht")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Regio-niveau", niveau)
c2.metric("Aantal gebieden", f"{len(map_df):,}")
c3.metric("Kleurvariabele", color_var)
c4.metric("SES-jaar", str(ses_year) if ses_year else "onbekend")

corr_candidates = [
    c for c in [
        color_var,
        height_var if height_var != "Geen" else None,
        size_var if size_var != "Geen" else None,
        "SES_WOA_score",
    ]
    if c and c in map_df.columns
]
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
        map_df[preferred_cols + others].drop(
            columns=[c for c in ["jaar_num", "niveau"] if c in map_df.columns],
            errors="ignore",
        ),
        width="stretch",
        height=500,
    )
