#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_cwa.py  ——  中央氣象署 (CWA) 開放資料抓取 → 快取 JSON（v1 skeleton）

從 CWA 開放資料平臺抓取颱風警報／路徑潛勢／侵襲機率／雨量，整理成
build_advisory.py 需要的 typhoon_status.json，以及原始快取 rainfall_now.json。

⚠ 金鑰只放後端環境變數 CWA_API_KEY，前端永遠不觸碰。
⚠ 部分資料集的實際 JSON 欄位路徑需以真實回應驗證（見各 parse_* 的 TODO）；
   本檔為可運行骨架：抓不到 / 無金鑰 / 非颱風期間 → 寫出 active=false 的安全狀態，不中斷管線。

環境變數：
  CWA_API_KEY   CWA 授權碼（https://opendata.cwa.gov.tw 註冊免費取得）

用法：
  CWA_API_KEY=CWA-xxxx python3 scripts/fetch_cwa.py
  python3 scripts/fetch_cwa.py            # 無金鑰 → 寫出 active=false 狀態
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    requests = None

TZ = timezone(timedelta(hours=8))
BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
COUNTY = "雲林縣"
# 二崙／西螺參考點（田區包圍網中心）
REF_LAT, REF_LNG = 23.79, 120.44

DATASETS = {
    "typhoon_warning": "W-C0034-001",   # 颱風消息與警報
    "invasion_prob":   "W-C0034-003",   # 侵襲機率 / 72hr 暴風圈侵襲機率
    "path_potential":  "W-C0034-005",   # 颱風路徑潛勢預報
    "rainfall":        "O-A0002-001",   # 自動雨量站
    "temp_obs":        "O-A0001-001",   # 自動氣象站（含氣溫，供低溫/寒流事件）
    "township_fcst":   "F-D0047-025",   # 雲林縣未來 3 天天氣預報
}

# 天氣事件累積檔（K線標記用）；僅逐日「向前累積」真實觀測，不臆造歷史。
EVENTS_FILE = "weather_events.json"
EVENTS_KEEP_DAYS = 760          # 與行情約 2 年窗口相符
RAIN_HEAVY_MM = 80              # CWA 大雨特報：24hr 累積雨量達 80mm
RAIN_TORRENT_MM = 200          # CWA 豪雨：24hr 累積達 200mm
COLD_TEMP_C = 10               # 平地氣溫 ≤10°C 視為低溫/寒流量級


def cwa_get(dataid, **params):
    """呼叫 CWA REST API，回傳 records dict（失敗回 None）。"""
    key = os.environ.get("CWA_API_KEY")
    if not key or requests is None:
        return None
    url = f"{BASE}/{dataid}"
    params = {"Authorization": key, "format": "JSON", **params}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        # CWA 慣例：{ success, records: {...} }
        return j.get("records")
    except Exception as e:
        print(f"[fetch_cwa] {dataid} 抓取失敗：{e}", file=sys.stderr)
        return None


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ─────────────── 颱風解析（W-C0034-005 路徑潛勢；已用巴威真實回應校準） ───────────────
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cyclone_list(path_records):
    """取出所有活動中熱帶氣旋（records.TropicalCyclones.TropicalCyclone[]）。"""
    if not isinstance(path_records, dict):
        return []
    cont = path_records.get("TropicalCyclones") or path_records.get("tropicalCyclones") or {}
    tcs = (cont.get("TropicalCyclone") or cont.get("tropicalCyclone")) if isinstance(cont, dict) else None
    if isinstance(tcs, dict):
        tcs = [tcs]
    return tcs or []


def _forecast_track(tc):
    """未來逐時預報點：InitialTime+ForecastHour 為時間，Circle15ms.Radius 為 7 級暴風圈半徑。"""
    fd = tc.get("ForecastData") or tc.get("forecastData") or {}
    fixes = (fd.get("Fix") or fd.get("fix")) if isinstance(fd, dict) else None
    if isinstance(fixes, dict):
        fixes = [fixes]
    out = []
    for fx in fixes or []:
        lat = _num(fx.get("CoordinateLatitude"))
        lng = _num(fx.get("CoordinateLongitude"))
        if lat is None or lng is None:
            continue
        dt = _parse_cwa_time(str(fx.get("InitialTime") or ""))
        fh = _num(fx.get("ForecastHour"))
        t = dt + timedelta(hours=fh) if (dt and fh is not None) else dt
        c15 = fx.get("Circle15ms") or {}
        c25 = fx.get("Circle25ms") or {}
        out.append({"t": t, "lat": lat, "lng": lng,
                    "r15": _num(c15.get("Radius")) or 0.0 if isinstance(c15, dict) else 0.0,
                    "r25": _num(c25.get("Radius")) or 0.0 if isinstance(c25, dict) else 0.0,
                    "gust": _num(fx.get("MaxGustSpeed"))})
    return out


def eval_typhoon(path_records, now, ref_lat=REF_LAT, ref_lng=REF_LNG):
    """用逐時預報位置 + 暴風圈半徑，算對雲林的侵襲機率/到達時間。回傳最具威脅的颱風 dict 或 None。"""
    best = None
    for tc in _cyclone_list(path_records):
        name = tc.get("CwaTyphoonName") or tc.get("TyphoonName") or "颱風"
        track = _forecast_track(tc)
        if not track:
            continue
        min_dist = 1e9
        eta_iso = eta_text = gust = None
        prob = 0.0
        for p in track:
            d = haversine_km(ref_lat, ref_lng, p["lat"], p["lng"])
            min_dist = min(min_dist, d)
            r15 = p["r15"]
            if r15 and d <= r15 and eta_iso is None and p["t"] and p["t"] > now:
                eta_iso = p["t"].isoformat()
                eta_text = f"約 {round((p['t'] - now).total_seconds() / 3600)} 小時後"
                gust = p["gust"]
            if p["r25"] and d <= p["r25"]:
                pr = 0.9
            elif r15 and d <= r15:
                pr = 0.65
            elif r15 and d <= r15 + 100:
                pr = 0.35
            elif r15 and d <= r15 + 300:
                pr = 0.12
            else:
                pr = 0.0
            prob = max(prob, pr)
        # 暴風圈未覆蓋雲林時，僅以距離給極小「接近度」（不足以觸發搶收，僅供顯示）
        if prob == 0.0 and min_dist < 400:
            prob = round(0.12 * (1 - min_dist / 400), 2)
        # 精簡逐時軌跡（供前端以「田區座標」自算各地侵襲機率）：時間 ISO + 位置 + 暴風圈半徑
        track_out = [{"t": p["t"].isoformat() if p["t"] else None,
                      "lat": round(p["lat"], 3), "lng": round(p["lng"], 3),
                      "r15": round(p["r15"] or 0), "r25": round(p["r25"] or 0),
                      "gust": p["gust"]} for p in track]
        cand = {"name": name, "min_dist": round(min_dist), "invade_prob": round(prob, 2),
                "eta_iso": eta_iso, "eta_text": eta_text, "gust": gust, "track": track_out}
        if best is None or cand["invade_prob"] > best["invade_prob"] or \
                (cand["invade_prob"] == best["invade_prob"] and cand["min_dist"] < best["min_dist"]):
            best = cand
    return best


def parse_warning(warn_records, now, county=COUNTY):
    """W-C0034-001：是否有生效中、涵蓋雲林的颱風警報（排除『解除』與過期）。"""
    if not isinstance(warn_records, dict):
        return {"land_warning": False, "text": None}
    infos = warn_records.get("info")
    if isinstance(infos, dict):
        infos = [infos]
    for info in infos or []:
        hl = str(info.get("headline") or "")
        if "解除" in hl:
            continue
        exp = _parse_cwa_time(str(info.get("expires") or ""))
        if exp and exp < now:
            continue
        areas = info.get("area")
        if isinstance(areas, list):
            covers = any(county in str(a.get("areaDesc", "")) or "雲林" in str(a) for a in areas)
        elif isinstance(areas, dict):
            covers = county in str(areas.get("areaDesc", ""))
        else:
            covers = True
        if covers:
            return {"land_warning": True, "text": hl or "颱風警報"}
    return {"land_warning": False, "text": None}


def parse_rain_24h(records, county=COUNTY):
    """回傳雲林縣各雨量站中最大 24hr 累積雨量 mm（找不到回 None）。"""
    if not records:
        return None
    best = None

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            loc = o.get("CountyName") or o.get("countyName") or ""
            if county in str(loc) or "雲林" in str(loc):
                # TODO 驗證：24hr 累積常在 RainfallElement.Past24hr.Precipitation
                r = _dig(o, ["RainfallElement", "Past24hr", "Precipitation"])
                if r is None:
                    r = o.get("now") or o.get("past24hr")
                try:
                    v = float(r)
                    if best is None or v > best:
                        best = v
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(records)
    return best


def parse_rain_hours(records, path, county=COUNTY):
    """回傳雲林各雨量站中某時段(由 path 指定，如 Past1hr)最大累積雨量 mm。"""
    if not records:
        return None
    best = None

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            loc = o.get("CountyName") or o.get("countyName") or ""
            if county in str(loc) or "雲林" in str(loc):
                r = _dig(o, path)
                try:
                    v = float(r)
                    if best is None or v > best:
                        best = v
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(records)
    return best


def parse_temp_min(records, county=COUNTY):
    """回傳雲林各自動氣象站當前氣溫的最小值（°C），供低溫/寒流事件判定。找不到回 None。
    ⚠ 欄位路徑（WeatherElement.AirTemperature）需以真實 O-A0001-001 回應校準；-99 等無效值排除。"""
    if not records:
        return None
    best = None

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            loc = o.get("CountyName") or o.get("countyName") or ""
            if county in str(loc) or "雲林" in str(loc):
                t = _dig(o, ["WeatherElement", "AirTemperature"])
                if t is None:
                    t = o.get("TEMP") or o.get("AirTemperature")
                try:
                    v = float(t)
                    if v > -90 and (best is None or v < best):
                        best = v
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(records)
    return best


def accumulate_events(status, temp_min, now):
    """把今天的真實天氣事件（颱風/大雨/低溫）併入 weather_events.json（逐日向前累積，去重、保留 2 年窗口）。
    回傳 (全部事件 list, 今日新增 list)。不臆造歷史——只記錄當下觀測到的事實。"""
    today = now.strftime("%Y-%m-%d")
    old = []
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            j = json.load(f)
            old = j if isinstance(j, list) else (j.get("events") or [])
    except Exception:
        old = []

    ev = {}   # key = "date|type" -> {date,type,label}
    for e in old:
        if isinstance(e, dict) and e.get("date") and e.get("type"):
            ev[f"{e['date']}|{e['type']}"] = {"date": e["date"], "type": e["type"], "label": e.get("label", "")}

    todays = []
    # ① 颱風：對雲林進入搶收模式或有陸上警報
    if status.get("active") or status.get("land_warning"):
        lbl = status.get("name") or "颱風"
        if status.get("land_warning") and status.get("warning"):
            lbl = f"{lbl}・{status['warning']}"
        todays.append({"date": today, "type": "typhoon", "label": lbl})
    # ② 大雨/豪雨：雲林 24hr 累積雨量達門檻
    r24 = status.get("rain_24h_mm")
    if isinstance(r24, (int, float)) and r24 >= RAIN_HEAVY_MM:
        kind = "豪雨" if r24 >= RAIN_TORRENT_MM else "大雨"
        todays.append({"date": today, "type": "rain", "label": f"{kind} {round(r24)}mm"})
    # ③ 低溫/寒流：雲林平地氣溫達門檻
    if isinstance(temp_min, (int, float)) and temp_min <= COLD_TEMP_C:
        todays.append({"date": today, "type": "cold", "label": f"低溫 {round(temp_min)}℃"})

    for e in todays:
        ev[f"{e['date']}|{e['type']}"] = e

    cutoff = (now - timedelta(days=EVENTS_KEEP_DAYS)).strftime("%Y-%m-%d")
    out = sorted((e for e in ev.values() if e.get("date", "") >= cutoff),
                 key=lambda e: (e["date"], e["type"]))
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out, todays


def _dig(o, path):
    for k in path:
        if isinstance(o, dict) and k in o:
            o = o[k]
        else:
            return None
    return o


def _parse_cwa_time(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def _struct(o, depth=9):
    """回傳資料結構摘要（鍵名 + 型別 + 少量樣本），供校準欄位路徑用。"""
    if depth <= 0:
        return "…"
    if isinstance(o, dict):
        return {k: _struct(v, depth - 1) for k, v in list(o.items())[:25]}
    if isinstance(o, list):
        return {"__list_len__": len(o), "__item__": _struct(o[0], depth - 1)} if o else "[]"
    s = str(o)
    return f"{type(o).__name__}={s[:60]}"


def main():
    now = datetime.now(TZ)
    key_set = bool(os.environ.get("CWA_API_KEY"))

    warn = cwa_get(DATASETS["typhoon_warning"])
    inv = cwa_get(DATASETS["invasion_prob"])
    path = cwa_get(DATASETS["path_potential"])

    # 除錯：把三個颱風資料集的真實結構寫出，供校準 parse_*（欄位路徑當初標 TODO）
    try:
        with open("cwa_debug.json", "w", encoding="utf-8") as f:
            json.dump({"key_set": key_set, "generated": now.isoformat(),
                       "W-C0034-001_warning": _struct(warn),
                       "W-C0034-003_invasion": _struct(inv),
                       "W-C0034-005_path": _struct(path)},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[fetch_cwa] debug dump 失敗：{e}", file=sys.stderr)

    rain_recs = cwa_get(DATASETS["rainfall"], CountyName=COUNTY)

    def _rp(key):
        return parse_rain_hours(rain_recs, ["RainfallElement", key, "Precipitation"])
    rain1 = _rp("Past1hr")
    rain24 = parse_rain_24h(rain_recs)
    # 多時段累積雨量（1/3/6/12/24hr、2/3 日）——比只看 24hr 更準；欄位名以真實 API 校準
    rain_multi = {"h1": rain1, "h3": _rp("Past3hr"), "h6": _rp("Past6hr"),
                  "h12": _rp("Past12hr"), "h24": rain24,
                  "d2": _rp("Past2days"), "d3": _rp("Past3days")}

    typ = eval_typhoon(path, now)
    warn_info = parse_warning(warn, now)

    if typ:
        # 對雲林有威脅（發布警報 或 侵襲機率≥10%）才進「搶收模式」；否則只「追蹤中」
        threatening = warn_info["land_warning"] or (typ["invade_prob"] or 0) >= 0.10
        status = {
            "updated": now.strftime("%Y-%m-%d %H:%M"),
            "source": "CWA opendata (W-C0034-005 路徑潛勢)",
            "active": bool(threatening),
            "tracking": (not threatening),
            "name": typ["name"],
            "warning": (warn_info["text"] if warn_info["land_warning"]
                        else ("颱風接近中" if threatening else "追蹤中，對雲林暫無直接威脅")),
            "land_warning": warn_info["land_warning"],
            "invade_prob": typ["invade_prob"],
            "eta_iso": typ["eta_iso"],
            "eta_text": typ["eta_text"] or "追蹤中",
            "min_dist_km": typ["min_dist"],
            "rain_24h_mm": rain24,
            "rain_1h_mm": rain1,
            "rain": rain_multi,
            "forecast_gust_ms": typ["gust"],
            "track": typ["track"],
        }
    else:
        status = {
            "updated": now.strftime("%Y-%m-%d %H:%M"), "source": "CWA opendata",
            "active": False, "tracking": False, "name": None, "warning": None,
            "land_warning": False, "invade_prob": None, "eta_iso": None, "eta_text": None,
            "min_dist_km": None, "rain_24h_mm": rain24, "rain_1h_mm": rain1, "rain": rain_multi,
            "forecast_gust_ms": None, "track": None,
        }

    with open("typhoon_status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    # 累積真實天氣事件（K線標記）：颱風 + 大雨（已有 rain24）+ 低溫（需氣溫觀測）
    temp_recs = cwa_get(DATASETS["temp_obs"], CountyName=COUNTY)
    temp_min = parse_temp_min(temp_recs)
    events, todays = accumulate_events(status, temp_min, now)

    print(f"[fetch_cwa] key_set={key_set} typhoon={status['name']} active={status['active']} "
          f"tracking={status.get('tracking')} invade={status['invade_prob']} eta={status['eta_text']} "
          f"dist={status.get('min_dist_km')}km rain24={rain24} rain1={rain1} temp_min={temp_min}")
    print(f"[fetch_cwa] 天氣事件累積：共 {len(events)} 筆，今日新增 {len(todays)} 筆"
          + (f"（{'、'.join(e['type'] for e in todays)}）" if todays else ""))
    if not key_set:
        print("[fetch_cwa] 未設 CWA_API_KEY → active=false 安全狀態。", file=sys.stderr)


if __name__ == "__main__":
    main()
