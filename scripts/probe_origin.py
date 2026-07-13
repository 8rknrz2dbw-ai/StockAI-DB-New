#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探測：農業部/國家開放平台有沒有「產地價格」的開放資料集（API 或檔案）。
   本開發沙盒擋 data.moa.gov.tw，故此檔由 .github/workflows/probe-origin.yml 在 GitHub Actions（有外網）執行，
   輸出 origin_probe.json 並印出摘要供判讀。找到就據以寫正式 fetch；找不到＝政府沒開放產地價 API。"""
import json, sys, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; erlun-probe/1.0)"}
KEYWORDS = ["產地價格", "產地價", "產地行情"]
OUT = {"tried": [], "hits": []}


def try_get(url, params=None, note=""):
    rec = {"url": url, "params": params, "note": note}
    try:
        r = requests.get(url, params=params, headers=UA, timeout=45)
        rec["status"] = r.status_code
        rec["ctype"] = r.headers.get("content-type", "")
        rec["len"] = len(r.text)
        rec["sample"] = r.text[:1200]
        try:
            rec["json"] = r.json()
        except Exception:
            rec["json"] = None
    except Exception as e:
        rec["status"] = None
        rec["error"] = str(e)
    OUT["tried"].append({k: rec.get(k) for k in ("note", "url", "params", "status", "ctype", "len", "error")})
    return rec


def scan_json_for_keyword(obj, kw, path="", found=None):
    """遞迴找 JSON 裡含關鍵字的字串值，回傳 (path, value) 清單（找資料集標題/資源網址）。"""
    if found is None:
        found = []
    if len(found) > 40:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            scan_json_for_keyword(v, kw, f"{path}.{k}", found)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            scan_json_for_keyword(v, kw, f"{path}[{i}]", found)
    elif isinstance(obj, str):
        if kw in obj or "產地" in obj:
            found.append((path, obj[:200]))
    return found


# ── 1) 國家開放平台 data.gov.tw（權威目錄，含 MOA 資料）多種搜尋端點 ──
gov_endpoints = [
    ("https://data.gov.tw/api/v2/rest/dataset", lambda kw: {"q": kw, "limit": 20}),
    ("https://data.gov.tw/api/front/dataset/search", lambda kw: {"keyword": kw, "page": 1}),
    ("https://data.gov.tw/api/v1/rest/dataset", lambda kw: {"q": kw}),
    ("https://data.gov.tw/api/dataset/search", lambda kw: {"query": kw}),
]
for kw in KEYWORDS:
    for base, pf in gov_endpoints:
        rec = try_get(base, pf(kw), f"gov.tw:{kw}")
        if rec.get("json") is not None:
            hits = scan_json_for_keyword(rec["json"], kw)
            if hits:
                OUT["hits"].append({"source": base, "kw": kw, "matches": hits[:25]})
        time.sleep(0.4)

# ── 2) 農業部平台 data.moa.gov.tw 目錄/搜尋（候選端點） ──
moa_endpoints = [
    ("https://data.moa.gov.tw/api/v1/dataset", lambda kw: {"query": kw}),
    ("https://data.moa.gov.tw/Service/OpenData/DataList.aspx", lambda kw: {"keyword": kw}),
    ("https://data.moa.gov.tw/open_search.aspx", lambda kw: {"keyword": kw}),
]
for kw in KEYWORDS[:2]:
    for base, pf in moa_endpoints:
        rec = try_get(base, pf(kw), f"moa:{kw}")
        if rec.get("json") is not None:
            hits = scan_json_for_keyword(rec["json"], kw)
            if hits:
                OUT["hits"].append({"source": base, "kw": kw, "matches": hits[:25]})
        time.sleep(0.4)

with open("origin_probe.json", "w", encoding="utf-8") as f:
    json.dump(OUT, f, ensure_ascii=False, indent=2)

# ── 摘要（供 Action log 直接判讀） ──
print("=" * 60)
print("[probe] 端點測試結果：")
for t in OUT["tried"]:
    print(f"  status={t.get('status')} len={t.get('len')} {t.get('note')} -> {t.get('url')} {t.get('error','')}")
print("-" * 60)
if OUT["hits"]:
    print(f"[probe] 疑似『產地』相關命中 {len(OUT['hits'])} 組：")
    for h in OUT["hits"]:
        print(f"  來源 {h['source']} (kw={h['kw']})")
        for p, v in h["matches"][:15]:
            print(f"    {p} = {v}")
else:
    print("[probe] 沒有任何端點回傳含『產地』的資料集 → 可能沒有產地價開放 API/需改別的目錄。")
print("=" * 60)
