# CLAUDE.md — 二崙葉菜行情室 ＋ 颱風搶收預判系統

給未來 Claude 工作階段的專案指引。

## 這是什麼

雲林二崙／西螺葉菜農的兩件事，放在同一個純前端站台（GitHub Pages）：

1. **行情看板** — 讀西螺果菜市場批發行情，畫價量走勢與季節基準線。
2. **搶收預判** — 颱風/豪雨來襲前，整合 7 因子給「每塊田×每種菜」的搶收決策
   （照常／觀望／建議搶收／立即搶收）＋ deadline 倒數 ＋ 農藥安全期兩難警示。

七因子：①歷史天氣 ②歷史雨量 ③地勢高低 ④蔬菜收成時間 ⑤農藥滯留(PHI) ⑥颱風警報 ⑦颱風預判。

## 架構原則

- **純前端 + 後端排程快取**：`index.html` 不含任何金鑰，只讀後端排程產出的靜態 JSON。
  抓不到時一律退回示範資料、絕不白畫面（`loadPrices` / `loadAdvisory` 都有 shape 檢查 + try/catch）。
- **CWA / 水利署 API 需授權金鑰、CORS 不保證** → 金鑰只放後端（`CWA_API_KEY` 環境變數 /
  GitHub Actions Secret），前端永遠不觸碰。
- **動態 `ghBase`**：`resolveGhBase()` 在 `*.github.io` 下解析出 repo 根，前端由此讀 JSON。

## 檔案結構

```
index.html                    行情看板 + 搶收預判（雙分頁單頁），讀 veg_prices.json /
                              harvest_advisory.json / typhoon_status.json，皆可退回 demo
scripts/
  fetch_prices.py             抓農業部「農產品交易行情」公開資料（免金鑰）→ veg_prices.json
  fetch_cwa.py                抓 CWA 颱風/路徑潛勢/侵襲機率/雨量 → typhoon_status.json
  build_advisory.py           田區登記表 + 天氣 → 決策模型 → harvest_advisory.json（含 EV、schedule）
  notify.py                   挑急迫田 → LINE Messaging API / webhook 推播（去重；未設則 dry-run）
  requirements.txt            requests
data/
  fields.example.json         田區登記表範例（真實檔為 data/fields.json，已 gitignore）
.github/workflows/
  update-data.yml             每 30 分排程：fetch_cwa → build_advisory → notify → commit JSON
  ci.yml                      PR 檢查：py_compile + 決策 demo + notify dry-run + 前端關鍵元素
  pages.yml                   push main → 自動部署 GitHub Pages（configure-pages 自動啟用）
.env.example                  CWA_API_KEY / LINE / webhook 範例
```

前端會讀取（不存在時退回 demo）：`veg_prices.json`（既有 miner 產出）、
`harvest_advisory.json`、`typhoon_status.json`（本專案腳本產出），三者皆置於站台根。

## 決策模型 v1（build_advisory.py）

管線：`正規化 → B 硬約束閘門 → C 滅田風險R → D 時間軸求解 → A 決策合成`。

- **B 硬約束**：`PHI`（安全採收期，未到期不可上市，颱風逼近時凸顯「搶收超標 vs 不收滅田」兩難）、
  `成熟度`（未達門檻收了殘值過低 → 壓為觀望）。已實作。
- **C 風險 R**：`100 × P到達機率 × I風雨強度 × W淹水權重 × V作物脆弱`。已實作；
  **歷史類比校準（analog）留 v2 TODO**。
- **D 時間軸**：`deadline = 暴風到達 − 安全緩衝 − 淹水提前量 − 搶收工時`；工時裝不下 → `partial_pct`。已實作。
- **E 市場 EV（v3）**：早收落袋 vs 賭災後噴價期望值。接 `veg_prices.json` 取 `base_price`、
  以全區搶收比例套 lampFor 爆量壓價（`price_early_factor`）、以全區損失率套災後噴價（`spike_factor`）。已實作。
  （全區日成交量的精確 surge 校準留 TODO，目前用搶收田比例代理。）
- **F 全區搶收排程（v4）**：人力有限（`--teams` N 隊）下，跨多田以 EDF 貪婪排出搶收順序/時程，
  標出「來不及完收」的田並建議部分搶收/保田。輸出於 `harvest_advisory.json` 的 `schedule`。已實作。
  （嚴格最佳化排程／部分搶收價值最大化留 TODO。）

可調參數集中在 `build_advisory.py` 頂部（`GROWTH_DAYS` / `MATURITY_MIN` / `V_CROP` / `FLOOD_ADVANCE_H` 等）。

## ⚠ 上線前務必

- **PHI 逐藥×逐作物實查**：`data/fields.example.json` 的 `phi_days` 為量級示意，
  真實值須由農業部「植物保護資訊系統」/ 防檢署「農藥資訊服務網」查登記值寫入。**PHI 是法規硬限制，不可臆填。**
- **菠菜等作物生育日數**與 `fetch_cwa.py` 各 `parse_*` 的 CWA 實際 JSON 欄位路徑（標了 TODO），須以真實 API 回應校準。
- **雲林測站站號別寫死**：以 `O-A0001-001` / `C-B0074-002` 回應過濾雲林縣站點取當前有效站號。

## 本機測試

```bash
pip install -r scripts/requirements.txt
python3 scripts/build_advisory.py --fields data/fields.example.json --demo-typhoon   # 注入示範颱風
python3 scripts/fetch_cwa.py            # 需 CWA_API_KEY，否則寫 active=false
# 前端：直接開 index.html（無 JSON 會自動跑 demo）
```

## 分支慣例

- 開發分支：`claude/vegetable-harvest-weather-system-tjpqnj`
- 資料 JSON 由 `update-data.yml` 排程提交到 Pages 所服務的分支根（見 README 部署段）。
