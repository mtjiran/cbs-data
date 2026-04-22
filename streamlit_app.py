import streamlit as st
import pandas as pd
import requests

st.title("Ziekteverzuim (CBS) – laatste 10 jaar")

url = "https://opendata.cbs.nl/ODataApi/odata/83765NED/TypedDataSet"

response = requests.get(url)
data = response.json()["value"]

df = pd.DataFrame(data)

# Filter
df = df[df["Perioden"].str.contains("JJ")]
df = df[df["Perioden"] >= "2014JJ00"]

df["Jaar"] = df["Perioden"].str[:4]
df = df.sort_values("Jaar")

st.line_chart(df.set_index("Jaar")["Ziekteverzuim_1"])
