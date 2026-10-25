"""Build the 3D race-route page for the 2026-10-25 Evergreen half marathon.

Inputs
  --fit         Garmin FIT of the race
  --osm         directory with Overpass JSON dumps: buildings, water, green, roads (queries in OSM_QUERIES below)
  --template    tools/race_3d_template.html
  --css         maplibre-gl.css 4.7.1 (inlined)
  --out         output HTML (single file, data inlined)
  --standalone  wrap as a full document (GitHub Pages); omit for a claude.ai Artifact, which adds its own skeleton

Chip/watch alignment: official start-mat time 05:26:13, watch start 05:25:01 -> chip clock = watch t - 72 s.
Course km = GPS distance rescaled piecewise between the official timing mats (0, 9.7, 17.1 km, finish). Aid stations are read off the organiser's course map by eye
and are approximate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import fitparse
import pandas as pd

OSM_QUERIES = {
    "buildings": 'way/relation["building"](around:200,<route polyline>)',
    "water": 'natural=water, waterway=riverbank (ways+relations), waterway=river in bbox 25.026,121.505,25.085,121.582',
    "green": 'leisure=park in bbox; landuse=grass (around:400); leisure=pitch (around:300)',
    "roads": 'highway motorway..tertiary (+links) in bbox',
}

OFFICIAL_KM = 21.0975
MAT_OFFSET_S = 72          # watch t when crossing the start mat
PLAN_S_PER_KM = 475        # 7:55/km, middle of the agreed 7:50-8:00/km
CHIP = {"start": "05:26:13", "splits": [(9.7, 3999), (17.1, 7264), (OFFICIAL_KM, 9023)], "gun": 9097}

LANDMARKS = [  # name, en, lat, lon, kind  (OSM coordinates; footprint centroid where the OSM node is off-site)
    ("總統府", "Presidential Office", 25.04000, 121.51198, "landmark"),
    ("長榮海事博物館", "Evergreen Maritime Museum", 25.03866, 121.51876, "museum"),
    ("臺北府城東門", "East Gate", 25.03902, 121.51768, "landmark"),
    ("中正紀念堂", "CKS Memorial Hall", 25.03481, 121.52152, "landmark"),
    ("國家戲劇院", "National Theater", 25.03527, 121.51820, "culture"),
    ("國家音樂廳", "National Concert Hall", 25.03705, 121.51925, "culture"),
    ("華山1914文創園區", "Huashan 1914", 25.04458, 121.52879, "culture"),
    ("光華數位新天地", "Guang Hua Digital Plaza", 25.04513, 121.53210, "landmark"),
    ("林森公園", "Linsen Park", 25.05304, 121.52645, "park"),
    ("臺北市立美術館", "Taipei Fine Arts Museum", 25.07195, 121.52451, "museum"),
    ("台北故事館", "Taipei Story House", 25.07313, 121.52462, "culture"),
    ("圓山大飯店", "Grand Hotel", 25.07873, 121.52639, "landmark"),
    ("國民革命忠烈祠", "Martyrs' Shrine", 25.07951, 121.53289, "landmark"),
    ("大佳河濱公園", "Dajia Riverside Park", 25.07457, 121.53497, "park"),
    ("美堤河濱公園", "Meiti Riverside Park", 25.07404, 121.55866, "park"),
    ("迎風河濱公園", "Yingfeng Riverside Park", 25.07332, 121.55797, "park"),
    ("美麗華摩天輪", "Miramar", 25.08328, 121.55746, "landmark"),
    ("臺北松山機場", "Songshan Airport", 25.06768, 121.55335, "landmark"),
    ("彩虹河濱公園", "Rainbow Riverside Park", 25.06173, 121.57220, "park"),
    ("觀山河濱公園", "Guanshan Riverside Park", 25.06126, 121.57004, "park"),
    ("內湖科技園區", "Neihu Science Park", 25.07608, 121.57282, "landmark"),
]
BRIDGES = [
    ("中山橋", "Zhongshan Bridge", 25.07421, 121.52533),
    ("圓山大橋", "Yuanshan Bridge", 25.07548, 121.52397),
    ("松江大橋", "Songjiang Bridge", 25.07283, 121.52668),
    ("大直橋", "Dazhi Bridge", 25.07799, 121.54448),
    ("民權大橋", "Minquan Bridge", 25.06490, 121.57200),
    ("麥帥一橋", "MacArthur 1st Bridge", 25.05272, 121.57167),
    ("麥帥二橋", "MacArthur 2nd Bridge", 25.05638, 121.57157),
]
# course km, services (read off the organiser's map; approximate)
AID = [
    (0.0, "起點：醫護、飲水、廁所"), (3.0, "補給站"), (5.6, "醫護站"), (7.2, "補給站、廁所"),
    (9.1, "補給站、廁所"), (9.4, "醫護站"), (12.6, "補給站、廁所"), (13.6, "醫護站"),
    (14.6, "補給站、廁所（麥帥二橋下）"), (15.7, "醫護站"), (17.5, "補給站、廁所"),
    (18.9, "補給站、廁所"), (OFFICIAL_KM, "終點：醫護、飲水、廁所"),
]


def r5(x: float) -> float:
    return round(x, 5)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation with linear extrapolation at both ends."""
    i = 1
    while i < len(xs) - 1 and x > xs[i]:
        i += 1
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def load_track(fit: Path) -> pd.DataFrame:
    rows, t0 = [], None
    for m in fitparse.FitFile(str(fit)).get_messages("record"):
        d = m.get_values()
        if d.get("position_lat") is None:
            continue
        t0 = t0 or d["timestamp"]
        rows.append({
            "t": (d["timestamp"] - t0).total_seconds(),
            "lat": d["position_lat"] * 180 / 2**31, "lon": d["position_long"] * 180 / 2**31,
            "alt": d.get("enhanced_altitude"), "hr": d.get("heart_rate"), "d": d.get("distance"),
            "spd": d.get("enhanced_speed"),
            "cad": (d.get("cadence") or 0) * 2 + (d.get("fractional_cadence") or 0) * 2,
            "step": d.get("step_length"),
        })
    df = pd.DataFrame(rows).set_index("t")
    df = df.reindex(range(int(df.index.max()) + 1)).interpolate(limit_direction="both")
    df.index.name = "t"
    return df


def track_payload(df: pd.DataFrame) -> dict:
    df = df.assign(
        spd_s=df["spd"].rolling(15, center=True, min_periods=1).mean(),
        spd5=df["spd"].rolling(5, center=True, min_periods=1).mean(),
        hr_s=df["hr"].rolling(5, center=True, min_periods=1).mean(),
        cad_s=df["cad"].where(df["cad"] > 100).rolling(15, center=True, min_periods=1).median(),
        step_s=df["step"].where(df["step"] > 300).rolling(15, center=True, min_periods=1).median(),
        alt_s=df["alt"].rolling(9, center=True, min_periods=1).mean(),
    )
    # course km: GPS distance rescaled piecewise between the official timing mats (watch t = mat + chip)
    anchors_t = [MAT_OFFSET_S] + [MAT_OFFSET_S + c for _, c in CHIP["splits"]]
    anchors_km = [0.0] + [k for k, _ in CHIP["splits"]]
    anchors_d = [df.loc[t, "d"] for t in anchors_t]
    df["ckm"] = [float(x) for x in pd.Series(df["d"]).apply(
        lambda d: _interp(d, anchors_d, anchors_km))]
    s = df.iloc[::2]
    pts = {
        "t": s.index.tolist(),
        "lon": [round(v, 6) for v in s["lon"]], "lat": [round(v, 6) for v in s["lat"]],
        "ckm": [round(v, 4) for v in s["ckm"]],
        "spd": [round(v, 3) for v in s["spd_s"]],
        "hr": [round(v, 1) for v in s["hr_s"]],
        "cad": [round(v, 1) for v in s["cad_s"].bfill().ffill()],
        "step": [round(v) for v in s["step_s"].bfill().ffill()],
        "alt": [round(v, 1) for v in s["alt_s"]],
    }

    # walking / standing moments between the mats (5-s speed < 1.7 m/s for >= 6 s)
    chip_end = MAT_OFFSET_S + CHIP["splits"][-1][1]
    slow = (df["spd5"] < 1.7) & (df.index > MAT_OFFSET_S + 30) & (df.index < chip_end - 5)
    stops, start = [], None
    for t, v in slow.items():
        if v and start is None:
            start = t
        elif not v and start is not None:
            if t - start >= 6:
                mid = df.loc[(start + t) // 2]
                stops.append({"t": int(start), "dur": int(t - start), "ckm": round(mid["ckm"], 2),
                              "lon": round(mid["lon"], 6), "lat": round(mid["lat"], 6)})
            start = None

    def at_ckm(k: float) -> dict:
        i = int((df["ckm"] - k).abs().idxmin())
        return {"t": i, "lon": round(df.loc[i, "lon"], 6), "lat": round(df.loc[i, "lat"], 6)}

    km_marks = [{"km": k, **at_ckm(k)} for k in range(1, 22)]
    splits = []
    prev = MAT_OFFSET_S
    for k in list(range(1, 22)) + [OFFICIAL_KM]:
        t = at_ckm(k)["t"] if k != OFFICIAL_KM else chip_end
        seg = df.loc[prev:t]
        dist = (k - (splits[-1]["km"] if splits else 0))
        splits.append({"km": k, "chip": t - MAT_OFFSET_S, "pace": round((t - prev) / dist),
                       "hr": round(seg["hr"].mean()), "step": round(seg["step_s"].median()),
                       "cad": round(seg["cad_s"].median())})
        prev = t
    checks = []
    for k, chip in CHIP["splits"]:
        gps_chip = (chip_end if k == OFFICIAL_KM else at_ckm(k)["t"]) - MAT_OFFSET_S
        checks.append({"km": k, "chip": chip, "gps_chip": gps_chip, "plan": round(k * PLAN_S_PER_KM)})
    print("alignment check (official vs GPS-derived chip s):", [(c["km"], c["chip"], c["gps_chip"]) for c in checks])
    aid = [{"ckm": k, "label": lab, **{kk: v for kk, v in at_ckm(max(k, 0.02)).items() if kk != "t"}} for k, lab in AID]
    return {"pts": pts, "stops": stops, "kms": km_marks, "splits": splits, "checks": checks, "aid": aid,
            "mat": MAT_OFFSET_S, "chip_end": chip_end, "plan_s_per_km": PLAN_S_PER_KM, "official_km": OFFICIAL_KM,
            "gps_km": round(df["d"].max() / 1000, 3), "gun": CHIP["gun"]}


# ---------- OSM -> compact GeoJSON ----------

def ring_coords(geom: list[dict]) -> list[list[float]]:
    out = []
    for g in geom:
        c = [r5(g["lon"]), r5(g["lat"])]
        if not out or out[-1] != c:
            out.append(c)
    return out


def assemble(ways: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join open member ways into closed rings by shared endpoints."""
    rings, pool = [], [w[:] for w in ways if len(w) > 1]
    while pool:
        cur = pool.pop(0)
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, w in enumerate(pool):
                if w[0] == cur[-1]:
                    cur += w[1:]
                elif w[-1] == cur[-1]:
                    cur += w[::-1][1:]
                elif w[-1] == cur[0]:
                    cur = w + cur[1:]
                elif w[0] == cur[0]:
                    cur = w[::-1] + cur[1:]
                else:
                    continue
                pool.pop(i)
                changed = True
                break
        if len(cur) >= 4 and cur[0] == cur[-1]:
            rings.append(cur)
    return rings


def polygons(elements: list[dict]) -> list[tuple[dict, list]]:
    out = []
    for e in elements:
        tags = e.get("tags", {})
        if e["type"] == "way" and e.get("geometry"):
            ring = ring_coords(e["geometry"])
            if len(ring) >= 4 and ring[0] == ring[-1]:
                out.append((tags, [[ring]]))
        elif e["type"] == "relation":
            outer = [ring_coords(m["geometry"]) for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
            inner = [ring_coords(m["geometry"]) for m in e.get("members", []) if m.get("role") == "inner" and m.get("geometry")]
            outs, ins = assemble(outer), assemble(inner)
            if outs:
                out.append((tags, [[o] + (ins if len(outs) == 1 else []) for o in outs]))
    return out


def near_route(coords, route_ll, km: float) -> bool:
    lim = (km * 1000) ** 2
    for lon, lat in coords[:: max(1, len(coords) // 12)]:
        for rlon, rlat in route_ll:
            if ((lat - rlat) * 111000) ** 2 + ((lon - rlon) * 101000) ** 2 < lim:
                return True
    return False


def osm_payload(osm: Path, route_ll: list) -> dict:
    load = lambda k: json.loads((osm / f"{k}.json").read_text(encoding="utf-8"))["elements"]
    feats = {"buildings": [], "water": [], "green": [], "roads": []}
    for tags, polys in polygons(load("buildings")):
        h = None
        try:
            h = float(str(tags.get("height", "")).replace("m", "").strip())
        except ValueError:
            pass
        if h is None:
            try:
                h = float(tags.get("building:levels")) * 3.2
            except (TypeError, ValueError):
                h = 9.0
        for p in polys:
            feats["buildings"].append({"type": "Feature", "properties": {"h": round(min(h, 250), 1)},
                                       "geometry": {"type": "Polygon", "coordinates": p}})
    for tags, polys in polygons(load("water")):
        for p in polys:
            feats["water"].append({"type": "Feature", "properties": {},
                                   "geometry": {"type": "Polygon", "coordinates": p}})
    for e in load("water"):
        if e["type"] == "way" and e.get("tags", {}).get("waterway") == "river" and e.get("geometry"):
            feats["water"].append({"type": "Feature", "properties": {"line": 1},
                                   "geometry": {"type": "LineString", "coordinates": ring_coords(e["geometry"])}})
    for tags, polys in polygons(load("green")):
        for p in polys:
            if near_route(p[0], route_ll, 1.5):
                feats["green"].append({"type": "Feature", "properties": {},
                                       "geometry": {"type": "Polygon", "coordinates": p}})
    rank = {"motorway": 1, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4}
    for e in load("roads"):
        if e["type"] != "way" or not e.get("geometry"):
            continue
        hw = e["tags"]["highway"]
        line = ring_coords(e["geometry"])
        if len(line) > 1 and near_route(line, route_ll, 1.2):
            feats["roads"].append({"type": "Feature", "properties": {"r": rank.get(hw.replace("_link", ""), 4)},
                                   "geometry": {"type": "LineString", "coordinates": line}})
    for k, v in feats.items():
        print(k, len(v))
    return {k: {"type": "FeatureCollection", "features": v} for k, v in feats.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", type=Path, required=True)
    ap.add_argument("--osm", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--css", type=Path, required=True, help="maplibre-gl.css 4.7.1, inlined")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--standalone", action="store_true", help="emit a full HTML document")
    a = ap.parse_args()
    df = load_track(a.fit)
    track = track_payload(df)
    route_ll = list(zip(track["pts"]["lon"][::20], track["pts"]["lat"][::20]))
    data = {
        "race": {"name": "長榮馬拉松 半馬", "name_en": "EVA AIR Marathon 2026", "date": "2026-10-25", "chip": 9023, "gun": 9097},
        "track": track, "osm": osm_payload(a.osm, route_ll),
        "landmarks": [dict(zip(("name", "en", "lat", "lon", "kind"), x)) for x in LANDMARKS],
        "bridges": [dict(zip(("name", "en", "lat", "lon"), x)) for x in BRIDGES],
    }
    html = a.template.read_text(encoding="utf-8")
    html = html.replace("/*__MAPLIBRE_CSS__*/", a.css.read_text(encoding="utf-8"))
    html = html.replace('"__RACE_DATA__"', json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    if a.standalone:
        html = '<!doctype html>\n<html lang="zh-Hant">\n' + html + "</html>\n"
    a.out.write_text(html, encoding="utf-8")
    print("wrote", a.out, round(a.out.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
