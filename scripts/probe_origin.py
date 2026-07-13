#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探測：農業部開放平台有沒有「產地價格」開放資料集。輸出 origin_probe.json（含樣本＋抽出的資料集連結）。
   沙盒擋 data.moa.gov.tw，故由 .github/workflows/probe-origin.yml 於 GitHub Actions 執行。
   第2版：MOA 端點回 200(HTML)，改成抓 open_search 搜尋頁 HTML → 正則抽出資料集標題/連結/UnitId/API。"""
import json, re, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; erlun-probe/1.0)"}
OUT = {"searches": [], "datasets": []}


def get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=45)
        return r.status_code, r.text
    except Exception as e:
        return None, f"ERR {e}"


# ── MOA 資料開放平台搜尋頁（HTML）：抓「產地價格/產地價/產地行情」搜尋結果 ──
for kw in ["產地價格", "產地價", "產地行情", "產地"]:
    st, html = get("https://data.moa.gov.tw/open_search.aspx", {"keyword": kw})
    rec = {"kw": kw, "status": st, "len": len(html) if isinstance(html, str) else 0}
    if isinstance(html, str) and st == 200:
        # 抽出：資料集詳情連結（open_data_detail / dataset / DataFileService / FromM API）與其前後文字
        links = re.findall(r'href=["\']([^"\']*(?:open_data|dataset|DataFileService|FromM|OpenData)[^"\']*)["\']', html, re.I)
        # 抽出含「產地」的可讀文字片段
        chan = re.findall(r'>([^<>]{2,40}產地[^<>]{0,40})<', html)
        unitids = re.findall(r'UnitId=(\d+)', html)
        titles = re.findall(r'title=["\']([^"\']*產地[^"\']*)["\']', html)
        rec["links_sample"] = list(dict.fromkeys(links))[:30]
        rec["chandu_text"] = list(dict.fromkeys(chan))[:30]
        rec["unitids"] = list(dict.fromkeys(unitids))[:40]
        rec["titles"] = list(dict.fromkeys(titles))[:30]
        rec["head"] = html[:600]
    else:
        rec["head"] = (html or "")[:600]
    OUT["searches"].append(rec)
    time.sleep(0.5)

# ── 也試農業部資料平台的資料集清單 API（看是不是 JSON 目錄） ──
for url in ["https://data.moa.gov.tw/api/v1/dataset",
            "https://data.moa.gov.tw/Service/OpenData/DataList.aspx"]:
    st, txt = get(url)
    rec = {"url": url, "status": st, "len": len(txt) if isinstance(txt, str) else 0, "head": (txt or "")[:1500]}
    # 若含產地，抽出片段
    if isinstance(txt, str):
        rec["chandu_text"] = list(dict.fromkeys(re.findall(r'[^\s"<>]{0,30}產地[^\s"<>]{0,30}', txt)))[:30]
    OUT["datasets"].append(rec)
    time.sleep(0.5)

with open("origin_probe.json", "w", encoding="utf-8") as f:
    json.dump(OUT, f, ensure_ascii=False, indent=2)

print("=" * 60)
for s in OUT["searches"]:
    print(f"[search kw={s['kw']}] status={s['status']} len={s['len']}")
    if s.get("titles"):
        print("  產地標題:", s["titles"])
    if s.get("chandu_text"):
        print("  含產地文字:", s["chandu_text"][:15])
    if s.get("unitids"):
        print("  UnitId:", s["unitids"])
    if s.get("links_sample"):
        print("  連結:", s["links_sample"][:15])
print("-" * 60)
for d in OUT["datasets"]:
    print(f"[list {d['url']}] status={d['status']} len={d['len']} 產地={d.get('chandu_text')}")
print("=" * 60)
