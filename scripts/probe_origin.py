#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探測 v3：找「產地價格」開放資料集。data.gov.tw 多為 CKAN → 試 api/3/action/package_search；
   併試農業部 SPA 的資料 API 候選端點。dump 每個回應前 2500 字供判讀。→ origin_probe.json
   由 GitHub Actions（有外網）執行（沙盒擋 data.moa.gov.tw）。"""
import json, re, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; erlun-probe/1.0)"}


def get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=45)
        return r.status_code, r.text
    except Exception as e:
        return None, f"ERR {e}"


TESTS = [
    ("ckan_search", "https://data.gov.tw/api/3/action/package_search", {"q": "產地價格"}),
    ("ckan_search2", "https://data.gov.tw/api/3/action/package_search", {"q": "產地"}),
    ("gov_datasetapi", "https://data.gov.tw/api/v2/rest/dataset", {"q": "產地價格", "top": 10}),
    ("moa_ajax_list", "https://data.moa.gov.tw/api/OpenData/DataList", {"keyword": "產地價格"}),
    ("moa_ajax_search", "https://data.moa.gov.tw/api/open/DataSet/Search", {"keyword": "產地價格"}),
    ("moa_od_json", "https://data.moa.gov.tw/Service/OpenData/DataList.aspx", {"IsTransData": "1"}),
    # 農糧署農產品產銷資訊：即時產地價格查詢（可能的 API）
    ("afa_origin", "https://amis.afa.gov.tw/producePrice/ProducePriceMonthly.aspx", None),
]

OUT = {"tests": []}
for name, url, params in TESTS:
    st, txt = get(url, params)
    rec = {"name": name, "url": url, "params": params, "status": st,
           "len": len(txt) if isinstance(txt, str) else 0}
    if isinstance(txt, str):
        rec["head"] = txt[:2500]
        rec["count"] = re.findall(r'"count"\s*:\s*(\d+)', txt)[:3]
        rec["chandu"] = list(dict.fromkeys(re.findall(r'[^\s"<>{}\[\],]{0,20}產地[^\s"<>{}\[\],]{0,20}', txt)))[:30]
        # CKAN: 抽 dataset title
        rec["titles"] = list(dict.fromkeys(re.findall(r'"title"\s*:\s*"([^"]{2,60})"', txt)))[:30]
    OUT["tests"].append(rec)
    time.sleep(0.5)

json.dump(OUT, open("origin_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("=" * 60)
for t in OUT["tests"]:
    print(f"[{t['name']}] status={t['status']} len={t['len']} count={t.get('count')}")
    if t.get("titles"):
        print("   titles:", t["titles"][:15])
    if t.get("chandu"):
        print("   產地字樣:", t["chandu"][:15])
    print("   head:", (t.get("head") or "")[:220].replace("\n", " "))
print("=" * 60)
