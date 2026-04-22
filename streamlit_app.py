import streamlit as st
import pandas as pd
import cbsodata

st.set_page_config(page_title="CBS verzuimdata", layout="wide")
st.title("CBS verzuimdata")

TABLE = "80072NED"

@st.cache_data
def load_data():
    props = pd.DataFrame(cbsodata.get_meta(TABLE, "DataProperties"))

    period_col = props.loc[props["Title"] == "Perioden", "Key"].iloc[0]
    value_col = props.loc[
        props["Title"].str.contains("Ziekteverzuimpercentage", case=False, na=False),
        "Key"
    ].iloc[0]
    sector_col = props.loc[
        props["Title"].str.contains("Bedrijfskenmerken", case=False, na=False),
        "Key"
    ].iloc[0]

    size_match = props.loc[
        props["Title"].str.contains("Bedrijfsgrootte", case=False, na=False),
        "Key"
    ]
    size_col = size_match.iloc[0] if not size_match.empty else None

    df = pd.DataFrame(cbsodata.get_data(TABLE))
st.write(df[["bedrijfstak", "bedrijfsgrootte"]].drop_duplicates().head(20))

df[sector_col] = df[sector_col].astype(str)

    sector_meta = pd.DataFrame(cbsodata.get_meta(TABLE, sector_col))[["Key", "Title"]].copy()
    sector_meta["Key"] = sector_meta["Key"].astype(str)
    sector_meta = sector_meta.rename(columns={"Key": sector_col, "Title": "bedrijfstak"})
    
    df = df.merge(sector_meta, on=sector_col, how="left")
    df["bedrijfstak"] = df["bedrijfstak"].fillna(df[sector_col])
    
    if size_col:
        df[size_col] = df[size_col].astype(str)
    
        size_meta = pd.DataFrame(cbsodata.get_meta(TABLE, size_col))[["Key", "Title"]].copy()
        size_meta["Key"] = size_meta["Key"].astype(str)
        size_meta = size_meta.rename(columns={"Key": size_col, "Title": "bedrijfsgrootte"})
    
        df = df.merge(size_meta, on=size_col, how="left")
        df["bedrijfsgrootte"] = df["bedrijfsgrootte"].fillna(df[size_col])
    else:
        df["bedrijfsgrootte"] = None

    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    raw_period = df[period_col].astype(str)
    df["jaar"] = pd.to_numeric(raw_period.str.extract(r"(\d{4})")[0], errors="coerce")
    df["kwartaal"] = pd.to_numeric(raw_period.str.extract(r"KW(\d)")[0], errors="coerce")
    df["frequentie"] = raw_period.apply(lambda x: "Kwartaal" if "KW" in x else "Jaar")
    df["periode_label"] = raw_period
    df["sort_key"] = df["jaar"] * 10 + df["kwartaal"].fillna(0)

    df = df.dropna(subset=["jaar", value_col]).copy()

    return df, period_col, value_col


df, period_col, value_col = load_data()

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

filtered = df[
    (df["frequentie"] == freq) &
    (df["jaar"] >= year_range[0]) &
    (df["jaar"] <= year_range[1])
].copy()

# Alleen filteren op bedrijfsgrootte als die info echt nuttig is
size_options = sorted(
    filtered["bedrijfsgrootte"].dropna().astype(str).unique().tolist()
)

show_size_filter = not (
    len(size_options) == 0 or
    (len(size_options) == 1 and size_options[0].strip().lower() == "onbekend")
)

if show_size_filter:
    default_size = [
        next(
            (x for x in size_options if "totaal" in x.lower() or "alle" in x.lower()),
            size_options[0]
        )
    ]

    selected_sizes = st.sidebar.multiselect(
        "Bedrijfsgrootte",
        size_options,
        default=default_size
    )

    if selected_sizes:
        filtered = filtered[filtered["bedrijfsgrootte"].isin(selected_sizes)]
else:
    st.sidebar.caption("Bedrijfsgrootte niet beschikbaar in deze selectie")

sector_options = sorted(
    filtered["bedrijfstak"].dropna().astype(str).unique().tolist()
)

if not sector_options:
    st.warning("Geen bedrijfstakken beschikbaar voor deze filtercombinatie.")
    st.stop()

default_sector = next(
    (x for x in sector_options if "alle economische activiteiten" in x.lower()),
    sector_options[0]
)

selected_sectors = st.sidebar.multiselect(
    "Bedrijfstakken",
    sector_options,
    default=[default_sector]
)

if not selected_sectors:
    selected_sectors = [default_sector]

include_benchmark = st.sidebar.checkbox("Voeg benchmark totaal toe", value=True)

if include_benchmark and default_sector not in selected_sectors:
    selected_sectors = [default_sector] + selected_sectors

filtered = filtered[filtered["bedrijfstak"].isin(selected_sectors)]

if filtered.empty:
    st.warning("Geen data voor deze filters.")
    st.stop()
# -------------------------
# KPI'S
# -------------------------
latest_key = filtered["sort_key"].max()
all_keys = sorted(filtered["sort_key"].dropna().unique().tolist())
prev_key = all_keys[-2] if len(all_keys) > 1 else None

latest_df = filtered[filtered["sort_key"] == latest_key]
latest_avg = latest_df[value_col].mean()

delta = None
if prev_key is not None:
    prev_df = filtered[filtered["sort_key"] == prev_key]
    prev_avg = prev_df[value_col].mean()
    delta = latest_avg - prev_avg

latest_period = latest_df["periode_label"].iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Gemiddeld verzuim", f"{latest_avg:.1f}%")
c2.metric("Delta vs vorige periode", f"{delta:+.1f} pp" if delta is not None else "-")
c3.metric("Aantal bedrijfstakken", len(set(selected_sectors)))
c4.metric("Laatste periode", latest_period)

# -------------------------
# CHARTS
# -------------------------
period_order = (
    filtered.groupby("periode_label")["sort_key"]
    .max()
    .sort_values()
    .index
)

trend_df = filtered.pivot_table(
    index="periode_label",
    columns="bedrijfstak",
    values=value_col,
    aggfunc="mean"
).reindex(period_order)

latest_bar = (
    latest_df.groupby("bedrijfstak")[value_col]
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
# DATA
# -------------------------
st.subheader("Data")

table_df = filtered[
    ["periode_label", "bedrijfstak", "bedrijfsgrootte", value_col]
].sort_values(["periode_label", "bedrijfstak"])

st.dataframe(table_df, use_container_width=True)

csv = table_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Download selectie als CSV",
    data=csv,
    file_name="cbs_verzuim_selectie.csv",
    mime="text/csv"
)
