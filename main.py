import pathlib

import folium
import folium.plugins
import geopandas as gpd
import pandas as pd

import pyproj

pd.set_option("display.max_columns", None)

# MLS

df_mls = pd.read_json("https://mls.js2hgw.com/cellmap/mls44011.json").query(
    "188743680 <= cell < 190023680"
)

# 日時に変換

dt_now = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)

df_mls["created"] = pd.to_datetime(df_mls["created"], unit="s")
df_mls["updated"] = pd.to_datetime(df_mls["updated"], unit="s")

df_mls[["eNB", "LCID"]] = df_mls["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))

df_mls["id"] = df_mls["eNB"].astype(str) + "-" + df_mls["LCID"].astype(str)

df_mls["経過日数"] = (dt_now - df_mls["updated"]).dt.days

df_ehime = (
    df_mls.sort_values(by=["updated", "cell"])
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
            "経過日数",
        ]
    )
    .sort_values(by="cell")
    .reset_index(drop=True)
)

df_ehime

def enblcid_split(df_tmp):
    df0 = df_tmp.copy()

    df0["eNB-LCID"] = df0["eNB-LCID"].str.split()
    df1 = df0.explode("eNB-LCID")

    df1[["eNB", "LCID"]] = df1["eNB-LCID"].str.split("-", expand=True)

    df1["LCID"] = df1["LCID"].str.split(",")
    df2 = df1.explode("LCID").astype({"eNB": int, "LCID": int})

    df2["cell"] = df2.apply(lambda x: (x["eNB"] << 8) | x["LCID"], axis=1)

    df2 = df2.sort_values(["cell"]).reset_index(drop=True)

    return df2

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
        
        df_ehime.at[i, "name"] = t["場所"]
        df_ehime.at[i, "distance"] = n

        if n < 5000:
            idx.append(i)

dft = df_ehime.drop(set(idx)).copy()

# 180日以内
unknown = dft[dft["経過日数"] < 180].copy()

df0 = (
    pd.read_csv(
        "https://raku10ehime.github.io/map/ehime.csv", index_col=0, parse_dates=["更新日時"]
    )
    .dropna(how="all")
)

df_map = enblcid_split(df0.dropna(subset=["eNB-LCID"])).sort_values(by=["cell", "更新日時"]).reset_index(drop=True)

df_map

df1 = pd.merge(df_map, df_ehime, on="cell", how="left")

df1[["eNB", "LCID"]] = df1["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))
df1["id"] = df1["eNB"].astype(str) + "-" + df1["LCID"].astype(str)


df1["距離"] = df1.apply(lambda x: grs80.inv(x["経度"], x["緯度"], x.lon, x.lat)[2], axis=1)

df1["更新日時"].mask(df1["更新日時"] < df1.updated, df1.updated, inplace=True)

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
    labels=["green", "lime", "yellow", "red", "black"],
    right=False,
)

df2

# 地図

colors = {
    0: "darkblue",
    1: "lightred",
    2: "lightgreen",
    3: "lightblue",
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
    tiles="https://area-map.mobile.rakuten.co.jp/5gs/geoserver/5g/mno_coverage_map/gwc/service/gmaps?LAYERS=mno_coverage_map:all_map&FORMAT=image/png&TRANSPARENT=TRUE&x={x}&y={y}&zoom={z}&update=20231130",
    fmt="image/png",
    attr="楽天モバイルエリア",
    tms=False,
    overlay=True,
    control=True,
    opacity=1,
    show=False,
).add_to(map)

folium.raster_layers.TileLayer(
    name="楽天モバイル（自社）",
    tiles="https://area-map.mobile.rakuten.co.jp/turbo/geoserver/4g/mno_coverage_map/gwc/service/gmaps?LAYERS=mno_coverage_map:all_map&FORMAT=image/png&TRANSPARENT=TRUE&&x={x}&y={y}&zoom={z}",
    fmt="image/png",
    attr="楽天モバイル（自社）",
    tms=False,
    overlay=True,
    control=True,
    opacity=1,
).add_to(map)

folium.raster_layers.TileLayer(
    name="au Band3",
    tiles="https://area.uqcom.jp/api2/4G_17/{z}/{x}/{y}.png",
    fmt="image/png",
    attr="au Band3エリア",
    tms=False,
    overlay=True,
    control=True,
    opacity=1,
).add_to(map)

fg1 = folium.FeatureGroup(name="未発見").add_to(map)
fg2 = folium.FeatureGroup(name="エリア外").add_to(map)
fg3 = folium.FeatureGroup(name="基地局").add_to(map)
fg4 = folium.FeatureGroup(name="更新状況").add_to(map)

for i, r in unknown.iterrows():
    
    if pd.isnull(r["distance"]):
    
        fg1.add_child(
            folium.Circle(
                location=[r.lat, r.lon],
                popup=folium.Popup(f'<p>{r["id"]}</p><p>{r["updated"]}</p><p>{r["name"]}</p><p>{r["distance"]}</p>', max_width=300),
                tooltip=f'<p>{r["id"]}</p><p>{r["updated"]}</p><p>{r["name"]}</p><p>{r["distance"]}</p>',
                radius=800,
                color=colors.get(r["LCID"] % 6),
            )
        )
    else:
        fg2.add_child(
            folium.Circle(
                location=[r.lat, r.lon],
                popup=folium.Popup(f'<p>{r["id"]}</p><p>{r["updated"]}</p><p>{r["name"]}</p><p>{r["distance"]}</p>', max_width=300),
                tooltip=f'<p>{r["id"]}</p><p>{r["updated"]}</p><p>{r["name"]}</p><p>{r["distance"]}</p>',
                radius=800,
                color="yellow",
            )
        )

for i, r in df0.iterrows():
    tag_map = f'<a href="https://www.google.com/maps?layer=c&cbll={r["緯度"]},{r["経度"]}" target="_blank" rel="noopener noreferrer">{r["場所"]}</a>'
    fg3.add_child(
        folium.Marker(
            location=[r["緯度"], r["経度"]],
            popup=folium.Popup(
                f'<p>{tag_map}</p><p>{r["緯度"]}, {r["経度"]}</p><p>{r["eNB-LCID"]}</p><p>{r["更新日時"]}</p>',
                max_width=300,
            ),
            icon=folium.Icon(color=r.color, icon=r.icon),
            place=r["場所"],
        )
    )

for i, r in df2.iterrows():
    fg4.add_child(
        folium.Marker(
            location=[r["緯度"], r["経度"]],
            popup=folium.Popup(
                f'<p>{r["場所"]}</p><p>{r["eNB-LCID"]}</p><p>{"<br />".join(r["更新日時"].split())}</p><p>{r["経過日数"]}</p>',
                max_width=300,
            ),
            tooltip=f'<p>{r["eNB-LCID"]}</p><p>{"<br />".join(r["更新日時"].split())}</p><p>{r["経過日数"]}</p>',
            icon=folium.plugins.BeautifyIcon(
                icon_shape="circle-dot", border_width=5, border_color=r["past_days"]
            ),
        )
    )

# 検索
folium.plugins.Search(
    layer=fg3,
    geom_type="Point",
    placeholder="場所検索",
    collapsed=True,
    search_label="place",
).add_to(map)

folium.LayerControl().add_to(map)
folium.plugins.LocateControl().add_to(map)

# クリック位置の緯度・経度表示
map.add_child(folium.LatLngPopup())

# map

map_path = pathlib.Path("map", "index.html")
map_path.parent.mkdir(parents=True, exist_ok=True)
map.save(map_path)
