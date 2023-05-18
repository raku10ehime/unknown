import pathlib

import folium
import folium.plugins
import geopandas as gpd
import pandas as pd

import pyproj

pd.set_option("display.max_columns", None)

# MLS

df_mls = pd.read_json("https://cellmap.rukihena.com/mls44011.json").query(
    "188743680 <= cell < 190023680"
)

# 緯度経度をgeometryに変換

pt_df = gpd.GeoDataFrame(
    df_mls, geometry=gpd.points_from_xy(df_mls.lon, df_mls.lat), crs="EPSG:6668"
)

ehime = gpd.read_file("N03-20220101_38_GML.zip").rename(
    columns={
        "N03_001": "都道府県名",
        "N03_002": "支庁・振興局名",
        "N03_003": "郡・政令都市名",
        "N03_004": "市区町村名",
        "N03_007": "行政区域コード",
    }
)

# geometryから市町村名を取得

spj = gpd.sjoin(pt_df, ehime)

# 日時に変換

spj["created"] = pd.to_datetime(spj["created"], unit="s")
spj["updated"] = pd.to_datetime(spj["updated"], unit="s")

spj[["eNB", "LCID"]] = spj["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))

spj["id"] = spj["eNB"].astype(str) + "-" + spj["LCID"].astype(str)

base = ehime.plot(color="white", edgecolor="black")
spj.plot(ax=base, marker="o", color="red", markersize=5)

spj

spj.columns

df_ehime = (
    spj.sort_values(by=["updated", "cell"])
    .drop_duplicates(subset=["cell"], keep="last")
    .reindex(
        columns=[
            "area",
            "lat",
            "lon",
            "created",
            "updated",
            "cell",
            "eNB",
            "LCID",
            "id",
            "市区町村名",
        ]
    )
    .sort_values(by="cell")
    .reset_index(drop=True)
)

df_ehime


def enblcid_split(df_tmp):
    df1 = df_tmp.copy()

    df1["eNB-LCID"] = df1["eNB-LCID"].str.split()
    df2 = df1.explode("eNB-LCID")

    df2[["eNB", "LCID"]] = df2["eNB-LCID"].str.split("-", expand=True)

    df2["LCID"] = df2["LCID"].str.split(",")
    df3 = df2.explode("LCID").astype({"eNB": int, "LCID": int})

    df3["cell"] = df3.apply(lambda x: (x["eNB"] << 8) | x["LCID"], axis=1)

    df3 = df3.sort_values(["cell"]).reset_index(drop=True)

    return df3


csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTuN5xiHhlnPTkv3auHkYLT9NPvvjayj5AdPrH5VBQdbELOzfONi236Vub6eSshv8jAxQw3V1rgbbgE/pub?gid=882951423&single=true&output=csv"

df_csv = pd.read_csv(
    csv_url, parse_dates=["更新日時"], usecols=["ID", "更新日時", "場所", "eNB-LCID", "地図"]
).dropna(how="all")

df_csv

df_csv[["lat", "lon"]] = df_csv["地図"].str.split(",", expand=True).astype(float)

df_enb = (
    enblcid_split(df_csv.dropna(subset=["eNB-LCID"]))
    .drop_duplicates(subset=["ID", "cell"], keep="last")
    .sort_values(by=["cell", "更新日時"])
    .reset_index(drop=True)
)

grs80 = pyproj.Geod(ellps="GRS80")

idx = []

for i, r in df_ehime.iterrows():
    df_tmp = df_enb[df_enb["cell"] == r.cell].copy()

    for j, t in df_tmp.iterrows():
        n = grs80.inv(r.lon, r.lat, t.lon, t.lat)[2]

        if n < 3000:
            idx.append(i)

unknown = df_ehime.drop(set(idx)).copy()

unknown.dtypes

unknown

df0 = (
    pd.read_csv(
        "https://raku10ehime.github.io/map/ehime.csv", index_col=0, parse_dates=["更新日時"]
    )
    .dropna(how="all")
    .dropna(subset=["eNB-LCID"])
)

df_map = enblcid_split(df0).sort_values(by=["cell", "更新日時"]).reset_index(drop=True)

df_map

df1 = pd.merge(df_map, df_ehime, on="cell", how="left")

df1[["eNB", "LCID"]] = df1["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))
df1["id"] = df1["eNB"].astype(str) + "-" + df1["LCID"].astype(str)

grs80 = pyproj.Geod(ellps="GRS80")

df1["距離"] = df1.apply(lambda x: grs80.inv(x["経度"], x["緯度"], x.lon, x.lat)[2], axis=1)

df1["更新日時"].mask(
    ((df1["更新日時"] < df1.updated) & (df1["距離"] < 2000)), df1.updated, inplace=True
)

dt_now = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)

df1["経過日数"] = (dt_now - df1["更新日時"]).dt.days

df1.sort_values(by=["cell"], inplace=True)

df1

df2 = (
    df1.groupby(by=["場所", "eNB-LCID", "緯度", "経度", "color", "icon"])
    .agg({"更新日時": [min, list], "経過日数": max})
    .droplevel(level=0, axis=1)
    .rename(columns={"min": "update", "list": "更新日時", "max": "経過日数"})
    .reset_index()
)

df2["更新日時"] = df2["更新日時"].apply(lambda x: "\n".join(i.strftime("%Y/%m/%d") for i in x))

df2["past_days"] = pd.cut(
    df2["経過日数"],
    [0, 90, 180, 360, 720, 99999],
    labels=["green", "yellow", "orange", "red", "black"],
    right=False,
)

df2

# 地図

colors = {
    0: "darkbule",
    1: "lightred",
    2: "lightgreen",
    3: "lightbule",
    4: "darkred",
    5: "darkgreen",
}

map = folium.Map(
    tiles=None,
    location=[34.06604300, 132.99765800],
    zoom_start=12,
)

folium.raster_layers.TileLayer(
    tiles="https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
    name="国土地理院",
    attr='&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
).add_to(map)

folium.raster_layers.TileLayer(
    name="楽天モバイル",
    tiles="https://area-map.mobile.rakuten.co.jp/dsd/geoserver/4g4m/mno_coverage_map/gwc/service/gmaps?LAYERS=mno_coverage_map:all_map&FORMAT=image/png&TRANSPARENT=TRUE&x={x}&y={y}&zoom={z}&update=20220404",
    fmt="image/png",
    attr="楽天モバイルエリア",
    tms=False,
    overlay=True,
    control=True,
    opacity=1,
).add_to(map)

fg1 = folium.FeatureGroup(name="未発見").add_to(map)

for i, r in unknown.iterrows():
    fg1.add_child(
        folium.Circle(
            location=[r.lat, r.lon],
            popup=folium.Popup(f'<p>{r["id"]}</p><p>{r["updated"]}</p>', max_width=300),
            tooltip=f'<p>{r["id"]}</p><p>{r["updated"]}</p>',
            radius=800,
            color=colors.get(r["LCID"] % 6),
        )
    )

fg2 = folium.FeatureGroup(name="基地局").add_to(map)
fg3 = folium.FeatureGroup(name="経過日数").add_to(map)

for i, r in df2.iterrows():
    fg2.add_child(
        folium.Marker(
            location=[r["緯度"], r["経度"]],
            popup=folium.Popup(
                f'<p>{r["場所"]}</p><p>{r["eNB-LCID"]}</p><p>{r["更新日時"]}</p>',
                max_width=300,
            ),
            icon=folium.Icon(color=r.color, icon=r.icon),
        )
    )

    fg3.add_child(
        folium.Marker(
            location=[r["緯度"], r["経度"]],
            popup=folium.Popup(
                f'<p>{r["場所"]}</p><p>{r["eNB-LCID"]}</p><p>{r["更新日時"]}</p>',
                max_width=300,
            ),
            icon=folium.plugins.BeautifyIcon(
                icon_shape="circle-dot", border_width=5, border_color=r["past_days"]
            ),
        )
    )

folium.LayerControl().add_to(map)
folium.plugins.LocateControl().add_to(map)

# map

map_path = pathlib.Path("map", "index.html")
map_path.parent.mkdir(parents=True, exist_ok=True)
map.save(map_path)
