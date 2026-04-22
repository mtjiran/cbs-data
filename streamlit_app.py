import streamlit as st
import pandas as pd
import cbsodata
from datetime import datetime

st.set_page_config(page_title="CBS verzuimdata", layout="wide")
st.title("CBS verzuimdata - afgelopen 10 jaar")

TABLE = "80072NED"

@st.cache_data
def load_verzuim():
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

    sector_meta = pd.DataFrame(cbsodata.get_meta(TABLE, sector_col))
    total_key = sector_meta.loc[
        sector_meta["Title"].str.contains("Alle economische activiteiten", case=False, na=False),
        "Key"
    ].iloc[0]

    df = pd.DataFrame(
        cbsodata.get_data(
            TABLE,
            filters=f"{sector_col} eq '{total_key}'"
        )
    )

    # Alleen jaarcijfers
    df = df[df[period_col].str.match(r"^\d{4}$")].copy()
    df["jaar"] = df[period_col].astype(int)

    current_year = datetime.now().year
    df = df[df["jaar"] >= current_year - 9].copy()

    df = df.sort_values("jaar")
    return df, value_col

df, value_col = load_verzuim()

st.line_chart(df.set_index("jaar")[value_col])
st.dataframe(df[["jaar", value_col]], use_container_width=True)
