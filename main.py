import pathlib

import folium
import folium.plugins
import geopandas as gpd
import pandas as pd

import pyproj

# MLS

df_mls = pd.read_json("https://cellmap.rukihena.com/mls44011.json")

# cellからeNB-LCIDを作成

df_mls[["eNB", "LCID"]] = df_mls["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))

# 日時に変換

df_mls["created"] = pd.to_datetime(df_mls["created"], unit="s")
df_mls["updated"] = pd.to_datetime(df_mls["updated"], unit="s")

# 90日以内

dt_now = (
    pd.Timestamp.now(tz="Asia/Tokyo")
    .tz_localize(None)
    .replace(hour=0, minute=0, second=0, microsecond=0)
)

dt_90d = dt_now - pd.Timedelta(days=90)
df_mls = df_mls[df_mls["updated"] > dt_90d].query("737280 <= eNB < 742280")

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

spj["id"] = spj["eNB"].astype(str) + "-" + spj["LCID"].astype(str)

base = ehime.plot(color="white", edgecolor="black")
spj.plot(ax=base, marker="o", color="red", markersize=5)

df_ehime = spj.reindex(
    columns=[
        "area",
        "lat",
        "lon",
        "created",
        "updated",
        "cell",
        "id",
        "eNB",
        "LCID",
        "geometry",
        "市区町村名",
    ]
).query("737280 <= eNB < 742280")

df_ehime.reset_index(drop=True, inplace=True)

df_ehime

# エリアマップ

def enblcid_split(df0):

    df0["eNB-LCID"] = df0["eNB-LCID"].str.split()
    df1 = df0.explode("eNB-LCID")

    df1[["eNB", "LCID"]] = df1["eNB-LCID"].str.split("-", expand=True)

    df1["LCID"] = df1["LCID"].str.split(",")
    df2 = df1.explode("LCID").astype({"eNB": int, "LCID": int})

    df2["cell"] = df2.apply(lambda x: (x["eNB"] << 8) | x["LCID"], axis=1)
    df2[["lat", "lon"]] = df2["地図"].str.split(",", expand=True).astype(float)

    df3 = df2.sort_values(["cell"]).reset_index(drop=True)

    return df3

# CSV

csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTuN5xiHhlnPTkv3auHkYLT9NPvvjayj5AdPrH5VBQdbELOzfONi236Vub6eSshv8jAxQw3V1rgbbgE/pub?gid=882951423&single=true&output=csv"


df_csv = pd.read_csv(
    csv_url, parse_dates=["更新日時"], usecols=["ID", "更新日時", "場所", "eNB-LCID", "地図"]
).dropna(how="all")

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

base = ehime.plot(color="white", edgecolor="black")
unknown.plot(ax=base, marker="o", color="red", markersize=5)

df_map = pd.read_csv("https://raku10ehime.github.io/map/ehime.csv", index_col=0, parse_dates=["更新日時"]).dropna(how="all")

df_map.dtypes

df_map["経過日数"] = (dt_now - df_map["更新日時"]).dt.days

df_map["past_days"] = pd.cut(df_map["経過日数"], [0, 90, 180, 360, 720, 99999], labels=["green", "yellow", "orange", "red", "black"], right=False)

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
fg3 = folium.FeatureGroup(name="").add_to(map)

for i, r in df_map.iterrows():

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
            icon=folium.plugins.BeautifyIcon(icon_shape="circle-dot", border_width=5, border_color=r["past_days"]),
        )
    )

folium.LayerControl().add_to(map)
folium.plugins.LocateControl().add_to(map)

# map

map_path = pathlib.Path("map", "index.html")
map_path.parent.mkdir(parents=True, exist_ok=True)
map.save(map_path)
