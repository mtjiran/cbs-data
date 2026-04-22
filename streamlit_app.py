import streamlit as st
import pandas as pd
import cbsodata
import json
from openai import OpenAI

st.set_page_config(page_title="CBS verzuimdata", layout="wide")
st.title("CBS verzuimdata")

TABLE = "80072NED"


def classify_dim(label: str) -> str:
    s = str(label).lower()
    if "werkzame personen" in s:
        return "Bedrijfsgrootte"
    return "Bedrijfstype"


@st.cache_data
def load_data():
    props = pd.DataFrame(cbsodata.get_meta(TABLE, "DataProperties"))

    period_col = props.loc[props["Title"] == "Perioden", "Key"].iloc[0]
    value_col = props.loc[
        props["Title"].str.contains("Ziekteverzuimpercentage", case=False, na=False),
        "Key"
    ].iloc[0]
    feature_col = props.loc[
        props["Title"].str.contains("Bedrijfskenmerken", case=False, na=False),
        "Key"
    ].iloc[0]

    df = pd.DataFrame(cbsodata.get_data(TABLE))

    df[feature_col] = df[feature_col].astype(str)

    feature_meta = pd.DataFrame(cbsodata.get_meta(TABLE, feature_col))[["Key", "Title"]].copy()
    feature_meta["Key"] = feature_meta["Key"].astype(str)
    feature_meta = feature_meta.rename(columns={"Key": feature_col, "Title": "bedrijfstak"})

    df = df.merge(feature_meta, on=feature_col, how="left")
    df["bedrijfstak"] = df["bedrijfstak"].fillna(df[feature_col])

    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    raw_period = df[period_col].astype(str)
    df["jaar"] = pd.to_numeric(raw_period.str.extract(r"(\d{4})")[0], errors="coerce")
    df["kwartaal"] = pd.to_numeric(raw_period.str.extract(r"KW(\d)")[0], errors="coerce")
    df["frequentie"] = raw_period.apply(lambda x: "Kwartaal" if "KW" in x else "Jaar")
    df["periode_label"] = raw_period
    df["sort_key"] = df["jaar"] * 10 + df["kwartaal"].fillna(0)

    df["dim_type"] = df["bedrijfstak"].apply(classify_dim)
    df["dim_value"] = df["bedrijfstak"].astype(str)

    df = df.dropna(subset=["jaar", value_col]).copy()

    global_total_label = next(
        (x for x in df["dim_value"].dropna().unique().tolist() if "alle economische activiteiten" in x.lower()),
        None
    )

    return df, value_col, global_total_label


df, value_col, global_total_label = load_data()

# -------------------------
# FILTERS
# -------------------------
st.sidebar.header("Filters")

freq = st.sidebar.radio("Weergave", ["Jaar", "Kwartaal"], index=0)

min_year = int(df["jaar"].min())
max_year = int(df["jaar"].max())
default_start = max(max_year - 9, min_year)

year_range = st.sidebar.slider(
    "Jaren",
    min_value=min_year,
    max_value=max_year,
    value=(default_start, max_year)
)

base_df = df[
    (df["frequentie"] == freq) &
    (df["jaar"] >= year_range[0]) &
    (df["jaar"] <= year_range[1])
].copy()

analyse_op = st.sidebar.radio(
    "Analyse op",
    ["Bedrijfstype", "Bedrijfsgrootte"],
    index=0
)

view_df = base_df[base_df["dim_type"] == analyse_op].copy()

options = sorted(view_df["dim_value"].dropna().unique().tolist())

if not options:
    st.warning("Geen opties beschikbaar voor deze analysekeuze.")
    st.stop()

default_option = next(
    (x for x in options if "alle economische activiteiten" in x.lower()),
    options[0]
)

selected_options = st.sidebar.multiselect(
    analyse_op,
    options,
    default=[default_option]
)

if not selected_options:
    selected_options = [default_option]

include_benchmark = st.sidebar.checkbox("Voeg benchmark totaal toe", value=True)

selected_df = view_df[view_df["dim_value"].isin(selected_options)].copy()

if include_benchmark and global_total_label:
    benchmark_df = base_df[base_df["dim_value"] == global_total_label].copy()
    selected_df = pd.concat([selected_df, benchmark_df], ignore_index=True).drop_duplicates()

if selected_df.empty:
    st.warning("Geen data voor deze filters.")
    st.stop()

# -------------------------
# KPI'S
# -------------------------
latest_key = selected_df["sort_key"].max()
all_keys = sorted(selected_df["sort_key"].dropna().unique().tolist())
prev_key = all_keys[-2] if len(all_keys) > 1 else None

latest_df = selected_df[selected_df["sort_key"] == latest_key].copy()
latest_selected_df = latest_df[latest_df["dim_value"].isin(selected_options)].copy()

latest_avg = latest_selected_df[value_col].mean()

delta = None
if prev_key is not None:
    prev_df = selected_df[selected_df["sort_key"] == prev_key].copy()
    prev_selected_df = prev_df[prev_df["dim_value"].isin(selected_options)].copy()
    prev_avg = prev_selected_df[value_col].mean()
    delta = latest_avg - prev_avg

latest_period = latest_df["periode_label"].iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Gemiddeld verzuim", f"{latest_avg:.1f}%")
c2.metric("Delta vs vorige periode", f"{delta:+.1f} pp" if delta is not None else "-")
c3.metric("Aantal categorieën", len(selected_options))
c4.metric("Laatste periode", latest_period)

# -------------------------
# CHARTS
# -------------------------
period_order = (
    selected_df.groupby("periode_label")["sort_key"]
    .max()
    .sort_values()
    .index
)

trend_df = selected_df.pivot_table(
    index="periode_label",
    columns="dim_value",
    values=value_col,
    aggfunc="mean"
).reindex(period_order)

latest_bar = (
    latest_df.groupby("dim_value")[value_col]
    .mean()
    .sort_values(ascending=False)
)

left, right = st.columns([2, 1])

with left:
    st.subheader("Trend")
    st.line_chart(trend_df)

with right:
    st.subheader(f"Laatste periode: {latest_period}")
    st.bar_chart(latest_bar)

# -------------------------
# DETAILTABEL
# -------------------------
st.subheader("Data")

table_df = selected_df[
    ["periode_label", "dim_type", "dim_value", value_col]
].sort_values(["periode_label", "dim_value"])

st.dataframe(table_df, use_container_width=True)

csv = table_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Download selectie als CSV",
    data=csv,
    file_name="cbs_verzuim_selectie.csv",
    mime="text/csv"
)
