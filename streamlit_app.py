import streamlit as st
import pandas as pd

st.title("Ziekteverzuim (CBS) – laatste 10 jaar")

url = "https://opendata.cbs.nl/ODataApi/odata/83765NED/TypedDataSet"

df = pd.read_json(url)

# Filter: alleen jaren + laatste 10 jaar
df = df[df["Perioden"].str.contains("JJ")]
df = df[df["Perioden"] >= "2014JJ00"]

# Jaar netjes maken
df["Jaar"] = df["Perioden"].str[:4]

# Chart
st.line_chart(df.set_index("Jaar")["Ziekteverzuim_1"])
