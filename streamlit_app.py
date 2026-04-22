import streamlit as st
import pandas as pd
import requests

st.title("Ziekteverzuim (CBS) – laatste 10 jaar")

BASE_URL_API = "https://opendata.cbs.nl/ODataApi/odata/83765NED/TypedDataSet"
BASE_URL_FEED = "https://opendata.cbs.nl/ODataFeed/odata/83765NED/TypedDataSet"


@st.cache_data
def load_cbs_filtered():
    """Snelste route: gefilterde query"""
    url = f"{BASE_URL_API}?$filter=BedrijfstakkenBranchesSBI2008 eq 'T001019'&$select=Perioden,Ziekteverzuim_1"

    r = requests.get(url)
    r.raise_for_status()

    data = r.json()["value"]
    df = pd.DataFrame(data)

    # laatste 10 jaar
    df = df[df["Perioden"].str.contains("JJ")]
    df["Jaar"] = df["Perioden"].str[:4].astype(int)
    df = df[df["Jaar"] >= df["Jaar"].max() - 9]

    return df.sort_values("Jaar")


@st.cache_data
def load_cbs_pagination():
    """Fallback als filter faalt"""
    all_rows = []
    skip = 0
    step = 1000

    while True:
        url = f"{BASE_URL_FEED}?$top={step}&$skip={skip}"
        r = requests.get(url)

        if r.status_code != 200:
            break

        data = r.json().get("value", [])
        if not data:
            break

        all_rows.extend(data)

        if len(data) < step:
            break

        skip += step

    df = pd.DataFrame(all_rows)

    df = df[df["Perioden"].str.contains("JJ")]
    df["Jaar"] = df["Perioden"].str[:4].astype(int)
    df = df[df["Jaar"] >= df["Jaar"].max() - 9]

    return df.sort_values("Jaar")


# --- MAIN LOGIC ---
try:
    df = load_cbs_filtered()
except Exception:
    st.warning("Filter faalde → fallback naar pagination")
    df = load_cbs_pagination()

# --- VISUAL ---
st.line_chart(df.set_index("Jaar")["Ziekteverzuim_1"])

# --- DEBUG (optioneel) ---
with st.expander("Data"):
    st.dataframe(df)
