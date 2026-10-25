# 2026 長榮半馬 3D 路徑

2026-10-25 長榮馬拉松（EVA AIR Marathon 2026）半程的個人比賽紀錄，以 3D 地圖呈現：晶片時間 2:30:23。

網站：https://wenlab501.github.io/my-running-route/

## 內容

- **3D 瀏覽**：沿賽道立起的指標牆，高度與顏色可各自選擇心率、配速、步幅、步頻或海拔；可回放（30×–300×）、鏡頭跟隨，並有一個以賽前計畫配速 7:55/km 前進的分身作對照。地圖標出公里牌、大會計時點、補給站與醫護站、走路停頓、附近地標與橋樑。下方圖表與地圖連動。
- **分段明細**：大會三段晶片配速、每公里數據、走路與停頓紀錄，以及資料說明。

頁面是單一 HTML 檔（`index.html`），資料內嵌，只從 cdnjs 載入 MapLibre GL JS 4.7.1、從 Google Fonts 載入字型。

## 資料

- 軌跡、配速、心率、步幅、步頻、海拔：作者本人 Garmin 手錶的比賽紀錄（每秒）。頁面公開這些資料是作者的選擇；原始 FIT 檔不在此 repo。
- 公里數：手錶量得 21.37 km，依大會 9.7 km、17.1 km 與終點三個計時點分段校正，回放時間與晶片時間一致。
- 補給站與醫護站：依大會路線圖目測標示，位置為概略值。
- 底圖（建築、河川、公園、道路、橋樑、地標）：© OpenStreetMap contributors，依 ODbL 授權，2026-10-25 經 Overpass API 擷取。

## 重新建置

```
uv sync
uv run python tools/build_race_3d.py --fit <race.fit> --osm <overpass_dumps_dir> \
  --template tools/race_3d_template.html --css <maplibre-gl-4.7.1.css> --out index.html --standalone
```

`--osm` 目錄需有 `buildings.json`、`water.json`、`green.json`、`roads.json` 四個 Overpass JSON（查詢條件見 `tools/build_race_3d.py` 的 `OSM_QUERIES`）。不加 `--standalone` 時輸出的是給 claude.ai Artifact 用的頁面片段。
