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
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=8))
API = "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"
UA = {"User-Agent": "Mozilla/5.0 (compatible; erlun-veg-advisory/1.0)"}

# 全台主要果菜批發市場（用短名做 API 過濾，較易匹配；對不到的自動略過，安全）。
MARKETS = ["台北一", "台北二", "三重", "板橋", "宜蘭", "桃園", "台中", "豐原",
           "南投", "溪湖", "永靖", "西螺", "北港", "嘉義", "高雄", "鳳山",
           "屏東", "台東", "花蓮"]

# 展示名 → 農業部作物名稱（批發端）。名稱須與 API「作物名稱」相符，
# 不符者該品項抓不到即安全略過。上線時可對照「農產品交易行情」實際名稱微調。
VEG_MAP = {
    "青江菜": "青江白菜", "小白菜": "小白菜", "芥藍菜": "芥藍菜", "菠菜": "菠菜",
    "空心菜": "蕹菜", "地瓜葉": "甘藷葉", "莧菜": "莧菜", "茼蒿": "茼蒿",
    "油菜": "油菜", "萵苣(A菜)": "萵苣菜", "芥菜": "芥菜",
}
# 水果（展示名 → 批發名）。⚠ 各批發名須以「農產品交易行情」實際作物名校準；
# 不符者抓不到即安全略過，前端不顯示。各地市場實際有交易的品項才會出現（達成「各地種類不同」）。
FRUIT_MAP = {
    "香蕉": "香蕉", "鳳梨": "鳳梨", "西瓜": "大西瓜", "木瓜": "木瓜",
    "蓮霧": "蓮霧", "芭樂": "番石榴", "葡萄": "葡萄", "椪柑": "椪柑",
    "柳丁": "柳橙", "火龍果": "紅龍果",
}
CROP_MAP = {**VEG_MAP, **FRUIT_MAP}                    # 抓取用（蔬菜+水果）
CATEGORIES = {**{d: "蔬菜" for d in VEG_MAP}, **{d: "水果" for d in FRUIT_MAP}}


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


def _latest_valid(series):
    """回傳最近一個 avg>0 的日期資料（附 date）；全為 0 時退回最新日。"""
    for dt in sorted(series, reverse=True):
        if (series[dt].get("avg") or 0) > 0:
            return {**series[dt], "date": dt}
    dt = max(series)
    return {**series[dt], "date": dt}


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

    os.makedirs("prices", exist_ok=True)
    index_markets, latest, total = [], {}, 0
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
            time.sleep(0.3)
        if not mdata:
            print(f"[fetch_prices] {mk}：無資料，略過。", file=sys.stderr)
            continue
        fname = f"prices/{len(index_markets) + 1:02d}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({"market": mk, "updated": now.strftime("%Y-%m-%d %H:%M"),
                       "crop_map": CROP_MAP, "data": mdata}, f, ensure_ascii=False)
        index_markets.append({"name": mk, "file": fname})
        # latest 取「最近一個有成交(avg>0)」的日期，避免當日休市/未成交的 0 元把該市場
        # 從全台跨市場比價中整個隱藏（前端 renderCompare 會濾掉 avg<=0）。
        latest[mk] = {c: _latest_valid(s) for c, s in mdata.items()}
        total += sum(len(s) for s in mdata.values())
        print(f"[fetch_prices] {mk}：{len(mdata)} 種、{sum(len(s) for s in mdata.values())} 筆 → {fname}")

    index = {"updated": now.strftime("%Y-%m-%d %H:%M"),
             "years_back": round(args.days / 365, 1),
             "crop_map": CROP_MAP,
             "categories": CATEGORIES,   # {展示名: 蔬菜|水果}（前端分類切換/比價分組用）
             "markets": index_markets,   # [{name, file}]
             "latest": latest}           # {market: {wholesale: {avg,high,mid,low,qty,date}}}
    with open("prices_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    print(f"[fetch_prices] 寫出 prices_index.json + {len(index_markets)} 個市場檔、共 {total} 筆行情")
    if not index_markets:
        print("[fetch_prices] ⚠ 全部市場 0 筆 —— 請確認 MARKETS/CROP_MAP 名稱（前端會退回示範資料）。",
              file=sys.stderr)


if __name__ == "__main__":
    main()
