import streamlit as st
import pandas as pd
import requests

st.title("Ziekteverzuim (CBS) – laatste 10 jaar")

BASE_URL = "https://opendata.cbs.nl/ODataApi/odata/83765NED/TypedDataSet"

years = [f"{y}JJ00" for y in range(2014, 2024)]
rows = []

for y in years:
    url = (
        f"{BASE_URL}"
        f"?$filter=Perioden eq '{y}' and BedrijfstakkenBranchesSBI2008 eq 'T001019'"
        f"&$top=1"
    )

    r = requests.get(url)

    if r.status_code != 200:
        st.error(f"Fout bij {y}")
        continue

    data = r.json().get("value", [])
    if data:
        rows.append(data[0])  # slechts 1 record nodig

df = pd.DataFrame(rows)

# Kolom check (CBS blijft inconsistent)
value_col = [col for col in df.columns if "Ziekteverzuim" in col][0]

df["Jaar"] = df["Perioden"].str[:4].astype(int)
df = df.sort_values("Jaar")

st.line_chart(df.set_index("Jaar")[value_col])
