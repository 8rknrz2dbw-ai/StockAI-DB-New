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
    "township_fcst":   "F-D0047-025",   # 雲林縣未來 3 天天氣預報
}


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


# ─────────────── 各資料集解析（best-effort；TODO 標註待驗證欄位路徑） ───────────────
def parse_typhoon_warning(records):
    """回傳 (active, name, warning_text, land_warning:bool)。"""
    if not records:
        return False, None, None, False
    # TODO 驗證：實際結構常為 records.typhoon[] 或 records.tropicalCyclones.tropicalCyclone[]
    tcs = (records.get("typhoon") or records.get("tropicalCyclones", {}).get("tropicalCyclone")
           or records.get("record") or [])
    if isinstance(tcs, dict):
        tcs = [tcs]
    if not tcs:
        return False, None, None, False
    tc = tcs[0]
    name = tc.get("typhoonName") or tc.get("cwaTyphoonName") or tc.get("cwaTdNo") or "颱風"
    # 警報種類文字（海上／海上陸上）——欄位名依實際回應調整
    wtxt = (tc.get("warningType") or tc.get("cwaWarningType")
            or tc.get("warning") or "颱風警報")
    land = "陸上" in str(wtxt)
    return True, name, wtxt, land


def parse_invasion_prob(records, county=COUNTY):
    """回傳雲林一帶 72hr 暴風圈侵襲機率 0..1（找不到回 None）。"""
    if not records:
        return None
    # TODO 驗證：常見於 records...['area'|'locations'] 內 {locationName, probability}
    def walk(o):
        found = []
        if isinstance(o, dict):
            ln = o.get("locationName") or o.get("countyName") or o.get("areaName")
            pr = o.get("probability") or o.get("value") or o.get("percent")
            if ln and pr is not None and (county in str(ln) or "雲林" in str(ln)):
                try:
                    found.append(float(str(pr).replace("%", "")))
                except ValueError:
                    pass
            for v in o.values():
                found += walk(v)
        elif isinstance(o, list):
            for v in o:
                found += walk(v)
        return found
    vals = walk(records)
    if not vals:
        return None
    p = max(vals)
    return round(p / 100 if p > 1 else p, 2)


def parse_path_eta(records, ref_lat=REF_LAT, ref_lng=REF_LNG):
    """由路徑潛勢逐時中心 + 暴風半徑，估暴風圈到達參考點的時間。
    回傳 (eta_iso, eta_text)。TODO：欄位路徑需以真實回應校準。"""
    if not records:
        return None, None
    # 嘗試抓出一串 {時間, 緯度, 經度, 七級暴風半徑km}
    fixes = []

    def walk(o):
        if isinstance(o, dict):
            lat = o.get("latitude") or o.get("lat")
            lng = o.get("longitude") or o.get("lon") or o.get("lng")
            t = (o.get("fixTime") or o.get("dateTime") or o.get("validTime")
                 or o.get("time"))
            rad = (o.get("radiusOf70PercentProbability")
                   or o.get("circleOfProbability") or o.get("radius"))
            if lat and lng and t:
                try:
                    fixes.append((str(t), float(lat), float(lng),
                                  float(rad) if rad else 250.0))
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(records)
    for tstr, lat, lng, rad in sorted(fixes, key=lambda x: x[0]):
        if haversine_km(ref_lat, ref_lng, lat, lng) <= rad:
            dt = _parse_cwa_time(tstr)
            if dt:
                hrs = round((dt - datetime.now(TZ)).total_seconds() / 3600)
                return dt.isoformat(), f"約 {hrs} 小時後"
    return None, None


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

    active, name, wtxt, land = parse_typhoon_warning(warn)

    invade_prob = eta_iso = eta_text = None
    if active:
        invade_prob = parse_invasion_prob(inv)
        eta_iso, eta_text = parse_path_eta(path)
    rain_recs = cwa_get(DATASETS["rainfall"], CountyName=COUNTY)
    rain24 = parse_rain_24h(rain_recs)
    rain1 = parse_rain_hours(rain_recs, ["RainfallElement", "Past1hr", "Precipitation"])   # 瞬間(1hr)雨量

    status = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "source": "CWA opendata",
        "active": bool(active),
        "name": name,
        "warning": wtxt,
        "land_warning": land,
        "invade_prob": invade_prob,
        "eta_iso": eta_iso,
        "eta_text": eta_text or ("警報中" if active else None),
        "rain_24h_mm": rain24,
        "rain_1h_mm": rain1,       # 瞬間(1hr)雨量：短延時強降雨→局部淹水指標
        "forecast_gust_ms": None,  # TODO v2：接 F-C0034-005 風力預測
    }
    with open("typhoon_status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"[fetch_cwa] typhoon_status.json：active={status['active']} "
          f"name={name} invade={invade_prob} eta={eta_text} rain24={rain24}")
    if not os.environ.get("CWA_API_KEY"):
        print("[fetch_cwa] 未設 CWA_API_KEY → 寫出 active=false 安全狀態（管線可繼續跑 demo）。",
              file=sys.stderr)


if __name__ == "__main__":
    main()
