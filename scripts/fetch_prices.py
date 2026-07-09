#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_prices.py  ——  抓農業部「農產品批發市場交易行情」公開資料 → veg_prices.json

免金鑰的公開 API。輸出 schema 與前端 index.html / build_advisory.py 既有約定一致：
  { updated, markets:[...], crop_map:{展示名:批發名}, data:{市場:{批發名:{ISO日:{avg,high,mid,low,qty}}}} }

⚠ 本開發沙盒的網路政策擋 data.moa.gov.tw，無法本機實測；於 GitHub Actions（有外網）執行，
   再由 Action log 驗證每個品項抓到幾筆。抓不到的品項會安全略過，前端自動不顯示、退回示範資料。

用法：
  python3 scripts/fetch_prices.py --days 365
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=8))
API = "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"
UA = {"User-Agent": "Mozilla/5.0 (compatible; erlun-veg-advisory/1.0)"}

# 要納入的果菜市場（可增減）。市場名稱須與 API 的「市場名稱」相符。
MARKETS = ["西螺", "台北一"]

# 展示名 → 農業部作物名稱（批發端）。名稱須與 API「作物名稱」相符，
# 不符者該品項抓不到即安全略過。上線時可對照「農產品交易行情」實際名稱微調。
CROP_MAP = {
    "青江菜": "青江白菜", "小白菜": "小白菜", "芥藍菜": "芥藍菜", "菠菜": "菠菜",
    "空心菜": "蕹菜", "地瓜葉": "甘藷葉", "莧菜": "莧菜", "茼蒿": "茼蒿",
    "油菜": "油菜", "萵苣(A菜)": "萵苣菜", "芥菜": "芥菜",
}


def roc(dt):
    """2026-07-08 → '115.07.08'（民國）"""
    return f"{dt.year - 1911:03d}.{dt.month:02d}.{dt.day:02d}"


def iso_from_roc(s):
    """'115.07.08' → '2026-07-08'"""
    try:
        y, m, d = s.split(".")
        return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def g(rec, *keys):
    for k in keys:
        v = rec.get(k) if isinstance(rec, dict) else None
        if v not in (None, "", "--"):
            return v
    return None


def fetch(market, crop, start, end):
    params = {"StartDate": roc(start), "EndDate": roc(end), "Market": market, "Crop": crop}
    r = requests.get(API, params=params, headers=UA, timeout=60)
    r.raise_for_status()
    try:
        j = r.json()
    except Exception:
        return []
    # 可能是 list，或包在 {"data":[...]} / {"RS":[...]}
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        return j.get("data") or j.get("RS") or j.get("Data") or []
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)   # 近 2 年，讓採收預判/走勢更穩
    ap.add_argument("--out", default="veg_prices.json")
    args = ap.parse_args()

    now = datetime.now(TZ)
    start = now - timedelta(days=args.days)

    data, used_markets = {}, []
    for mk in MARKETS:
        mdata = {}
        for disp, cname in CROP_MAP.items():
            try:
                recs = fetch(mk, cname, start, now)
            except Exception as e:
                print(f"[fetch_prices] {mk}/{cname} 抓取失敗：{e}", file=sys.stderr)
                recs = []
            series = {}
            for rec in recs or []:
                iso = iso_from_roc(str(g(rec, "交易日期", "TransDate") or ""))
                avg = g(rec, "平均價", "Avg_Price")
                if not iso or avg is None:
                    continue
                # 過濾市場名稱（Market 參數有時為模糊比對，double check）
                mn = str(g(rec, "市場名稱", "MarketName") or "")
                if mk not in mn and mn not in mk and mn:
                    continue
                try:
                    a = float(avg)
                    series[iso] = {
                        "avg": round(a, 1),
                        "high": round(float(g(rec, "上價", "Upper_Price") or a), 1),
                        "mid": round(float(g(rec, "中價", "Middle_Price") or a), 1),
                        "low": round(float(g(rec, "下價", "Lower_Price") or a), 1),
                        "qty": round(float(g(rec, "交易量", "Trans_Quantity") or 0)),
                    }
                except (TypeError, ValueError):
                    continue
            if series:
                mdata[cname] = series
                print(f"[fetch_prices] {mk} / {disp}（{cname}）：{len(series)} 筆")
            time.sleep(0.3)
        if mdata:
            data[mk] = mdata
            used_markets.append(mk)

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "years_back": round(args.days / 365, 1),
        "markets": used_markets,
        "crop_map": CROP_MAP,
        "data": data,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    total = sum(len(s) for m in data.values() for s in m.values())
    print(f"[fetch_prices] 寫出 {args.out}：{len(used_markets)} 個市場、共 {total} 筆行情")
    if total == 0:
        print("[fetch_prices] ⚠ 抓到 0 筆 —— 請確認 MARKETS / CROP_MAP 名稱與 API 相符"
              "（此時前端會退回示範資料，不會壞）。", file=sys.stderr)


if __name__ == "__main__":
    main()
