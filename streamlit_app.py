import streamlit as st
import pandas as pd
import requests
import io

st.set_page_config(page_title="CBS verzuimdata", layout="wide")
st.title("CBS verzuimdata")

URL = "https://datasets.cbs.nl/CSV/CBS/nl/80072ned"

@st.cache_data
def load_data():
    response = requests.get(URL, timeout=60)
    response.raise_for_status()

    raw = response.content

    text = None
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass

    if text is None:
        raise ValueError("Kon CBS-bestand niet decoderen.")

    df = pd.read_csv(io.StringIO(text), sep=";")
    df.columns = [c.strip() for c in df.columns]

    period_col = next(c for c in df.columns if "Perioden" in c)
    value_col = next(c for c in df.columns if "Ziekteverzuimpercentage" in c)
    sector_col = next(c for c in df.columns if "Bedrijfskenmerken" in c)
    size_col = next((c for c in df.columns if "Bedrijfsgrootte" in c), None)

    df[value_col] = (
        df[value_col]
        .astype(str)
        .str.replace(",", ".", regex=False)
    )
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    raw_period = df[period_col].astype(str)
    df["jaar"] = pd.to_numeric(raw_period.str.extract(r"(\d{4})")[0], errors="coerce")
    df["kwartaal"] = pd.to_numeric(raw_period.str.extract(r"KW(\d)")[0], errors="coerce")
    df["frequentie"] = raw_period.apply(lambda x: "Kwartaal" if "KW" in x else "Jaar")
    df["periode_label"] = raw_period
    df["sort_key"] = df["jaar"] * 10 + df["kwartaal"].fillna(0)

    return df, period_col, value_col, sector_col, size_col

df, period_col, value_col, sector_col, size_col = load_data()

# -----------------------
# SIDEBAR FILTERS
# -----------------------
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

df_filtered = df[
    (df["frequentie"] == freq) &
    (df["jaar"] >= year_range[0]) &
    (df["jaar"] <= year_range[1])
].copy()

if size_col:
    size_options = sorted(df_filtered[size_col].dropna().unique().tolist())
    default_size = [next((x for x in size_options if "totaal" in str(x).lower() or "alle" in str(x).lower()), size_options[0])]
    selected_sizes = st.sidebar.multiselect("Bedrijfsgrootte", size_options, default=default_size)
    df_filtered = df_filtered[df_filtered[size_col].isin(selected_sizes)]

sector_options = sorted(df_filtered[sector_col].dropna().unique().tolist())
default_sector = next((x for x in sector_options if "alle economische activiteiten" in str(x).lower()), sector_options[0])

selected_sectors = st.sidebar.multiselect(
    "Bedrijfstakken",
    sector_options,
    default=[default_sector]
)

include_benchmark = st.sidebar.checkbox("Voeg benchmark totaal toe", value=True)

if include_benchmark and default_sector not in selected_sectors:
    selected_sectors = [default_sector] + selected_sectors

df_filtered = df_filtered[df_filtered[sector_col].isin(selected_sectors)]

if df_filtered.empty:
    st.warning("Geen data voor deze filters.")
    st.stop()

# -----------------------
# KPI'S
# -----------------------
latest_key = df_filtered["sort_key"].max()
all_keys = sorted(df_filtered["sort_key"].dropna().unique().tolist())
prev_key = all_keys[-2] if len(all_keys) > 1 else None

latest_df = df_filtered[df_filtered["sort_key"] == latest_key]
latest_avg = latest_df[value_col].mean()

prev_avg = None
delta = None
if prev_key is not None:
    prev_df = df_filtered[df_filtered["sort_key"] == prev_key]
    prev_avg = prev_df[value_col].mean()
    delta = latest_avg - prev_avg

latest_period = latest_df["periode_label"].iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Gemiddeld verzuim", f"{latest_avg:.1f}%")
c2.metric("Delta vs vorige periode", f"{delta:+.1f} pp" if delta is not None else "-")
c3.metric("Aantal bedrijfstakken", len(set(selected_sectors)))
c4.metric("Laatste periode", latest_period)

# -----------------------
# CHART DATA
# -----------------------
period_order = (
    df_filtered.groupby("periode_label")["sort_key"]
    .max()
    .sort_values()
    .index
)

trend_df = df_filtered.pivot_table(
    index="periode_label",
    columns=sector_col,
    values=value_col,
    aggfunc="mean"
).reindex(period_order)

latest_bar = (
    latest_df.groupby(sector_col)[value_col]
    .mean()
    .sort_values(ascending=False)
)

# -----------------------
# LAYOUT
# -----------------------
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Trend")
    st.line_chart(trend_df)

with col_right:
    st.subheader(f"Laatste periode: {latest_period}")
    st.bar_chart(latest_bar)

# -----------------------
# TABEL + DOWNLOAD
# -----------------------
st.subheader("Data")

show_cols = ["periode_label", sector_col, value_col]
if size_col:
    show_cols.insert(2, size_col)

table_df = df_filtered[show_cols].sort_values(["periode_label", sector_col])

st.dataframe(table_df, use_container_width=True)

csv = table_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Download selectie als CSV",
    data=csv,
    file_name="cbs_verzuim_selectie.csv",
    mime="text/csv"
)
