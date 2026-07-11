# CLAUDE.md — 精準務農（原「農商雷達／豐雨無阻／二崙葉菜行情室」）＋ 颱風搶收預判系統

給未來 Claude 工作階段的專案指引。

## ⚑ 已拆成兩支 App（2026-07 起）

原本一份程式碼用「蔬果農／商人」角色切換，已依用戶要求**拆成兩支獨立 App**：

- **精準務農（farmer）** — 這個 GitHub repo／Pages 就是它。行情看板＋田區搶收＋採收預判。
- **精準進貨（merchant）** — 另一支獨立 App（批發行情＋跨市場比價找便宜進貨），
  以打包 zip 交付、由用戶另外部署（不在此 repo）。

實作方式：`index.html` 頂端有 `const APP="farmer"`（另一支為 `"merchant"`）與 `APP_NAME`。
`S.role` 固定回傳 `APP`、不可切換；`singleRoleUI()` 於啟動時隱藏「角色」切換與另一身分才用的設定
（商人版另隱藏「我的田區」、把「天氣與田區」改標「天氣」）。分頁與天氣建議、買賣價註記本就依 `S.role`
gating，角色固定後即自動只顯示該身分的功能。兩支 App 共用同一份 `index.html` 邏輯，只差 `APP` 常數與
各檔靜態名稱（title/meta/manifest/privacy/terms/sw CACHE）。改動邏輯時**兩支都要同步**。

## 這是什麼

雲林二崙／西螺葉菜農的兩件事，放在同一個純前端站台（GitHub Pages）：

1. **行情看板** — 讀西螺果菜市場批發行情，畫價量走勢與季節基準線。
2. **搶收預判** — 颱風/豪雨來襲前，整合 7 因子給「每塊田×每種菜」的搶收決策
   （照常／觀望／建議搶收／立即搶收）＋ deadline 倒數 ＋ 農藥安全期兩難警示。

七因子：①歷史天氣 ②歷史雨量 ③地勢高低 ④蔬菜收成時間 ⑤農藥滯留(PHI) ⑥颱風警報 ⑦颱風預判。

## 架構原則

- **純前端 + 後端排程快取**：`index.html` 不含任何金鑰，只讀後端排程產出的靜態 JSON。
  抓不到時一律退回示範資料、絕不白畫面（`loadIndex` / `loadMarket` / `loadWeather` /
  `loadEvents` 都有 shape 檢查 + try/catch，失敗回 demo 或空物件）。
- **CWA / 水利署 API 需授權金鑰、CORS 不保證** → 金鑰只放後端（`CWA_API_KEY` 環境變數 /
  GitHub Actions Secret），前端永遠不觸碰。
- **動態 `ghBase`**：`resolveGhBase()` 在 `*.github.io` 下解析出 repo 根，前端由此讀 JSON。

## 檔案結構

```
index.html                    單頁多分頁：行情看板／田區搶收／採收預判／跨市場比價(compare)。
                              角色可切「蔬果農／商人」(商人看批發、compare 分頁)。字體 s/m/l/xl。
                              行情看板為「大卡列表→點進去詳細頁」：詳細頁含 K線走勢(日/週/月·2年·查價線
                              ＋Y軸最高/最低刻度隨單位換算)＋「農產品交易行情」逐日明細卡(均價/上/中/下價/
                              漲跌/成交量/農曆)，全站可切公斤/台斤(1台斤=0.6kg，S.unit)。看板頂有搜尋框
                              (跨市場全部品項、不分蔬果)＋市場標示；預設看板優先列常見葉菜(COMMON_VEG)再補量大者。
                              農曆用內建 solar→lunar(2020-2035 表，已對節氣校驗)。
                              颱風警戒卡可點開「颱風詳情」modal：自氣象署逐時軌跡繪相對雲林的路徑圖(暴風圈)
                              ＋windy 雷達 iframe＋NCDR/windy 連結。地圖 CHINA 多邊形內陸封口拉遠(緯46/lng100)
                              →海岸線永遠不被畫面切成一半。
                              有品種的作物(如鳳梨)點卡片先下拉選品種(全部綜合/金鑽/牛奶…)再進 K線。
                              品項圖示：蔬菜插圖已全面取消(改 emoji)；水果用放大鏡(SEARCH_SVG)。點任一品項圖示都開
                              「說明」彈窗(cropIconHTML/wireIcon→openCropInfo)：內有挑選要訣＋「用 Google 查詢實際
                              照片」鈕(ciSearch，水果標題帶品項名)。零版權不自存圖。CROP_SVG 保留但已不使用。
                              頁首：實際·示範 badge 靠左、其右接更新日期、⚙️最右。App 名農商雷達見 PWA/頁尾。
                              App 圖示 icon.svg/PNG 為自繪「雷達準星弧＋雙葉幼苗(漸層)＋扇形田壟」綠徽(依用戶圖例)。
                              全站兩指可縮放放大檢視、放開回彈原狀(純視覺 transform scale；pageshow 清殘留 transform)。
                              全國定位：颱風侵襲機率依「所在縣市」中心點×颱風軌跡計算(regionInvasion，不寫死雲林)；
                              文案改「全台蔬果」。設定分五類(顯示與身分/行情看板/天氣與田區/資料備份/關於)；我的品項
                              蔬菜·水果各自「全選/取消全選」＋計數；田區表單附「Google Earth 量田」教學＋地勢等級海拔參考。
                              設定「資料備份／換手機」可匯出/匯入所有 vs_* 為單一 .json(collectBackup/importData，
                              navigator.share 檔案優先→退回 a[download]；安卓/iOS 皆可)。
                              首次啟動有「蔬果農/商人」身分選擇獨立介面(vs_onboarded，設定仍可改)。
                              天氣為全國：設定有「天氣預報地區」縣市選單(S.region，預設雲林縣)；農夫若有填
                              座標的田自動以田所在縣市為準(activeCounty/countyFromLatLng，COUNTY_LL 22縣市中心)。
                              預報以「今日白天/今晚/明日白天」時段卡呈現(天氣emoji＋降雨機率＋高低溫)。
                              設定內「關於 App」(上架用、可摺疊)：意見回饋(mailto)/常見問題(FAQ modal)/隱私權
                              政策(privacy.html)/使用條款(terms.html)/分享App(navigator.share→剪貼簿退回)。
                              App 圖示(icon.svg/PNG)為自繪「雷達準星＋幼苗＋田壟」綠色徽章，扣合「農商雷達」。
                              PWA：manifest.json+sw.js+icon，可加到主畫面、離線可用。
                              讀 prices_index.json + prices/NN.json / typhoon_status.json /
                              weather_events.json / weather_forecast.json / harvest_advisory.json，全部可退回 demo。
privacy.html / terms.html     隱私權政策／使用條款靜態頁(上架必備)。誠實：無帳號、不收個資、GPS 僅本機、
                              資料採政府公開資料；建議/PHI/產量係數僅供參考，勿臆填。聯絡 xin7355@gmail.com。
scripts/
  fetch_prices.py             抓農業部「農產品交易行情」（免金鑰，近 2 年）→ prices_index.json
                              （markets/crop_map/categories/latest）+ prices/NN.json（data + variants）。
                              **逐市場抓全部**：每市場一次 query(不帶作物名)拿回所有成交品項(17 次請求,
                              取代逐品項的上千次)。用回應的「種類代碼」自動分蔬菜/水果、濾掉花卉/休市/0 元。
                              作物名以 norm_crop() 收斂到母作物(鳳梨-金鑽→鳳梨)、量加權合併；同時把各品種
                              的「完整逐日序列」存到 variants[母作物]={品種:{iso:{avg..}}}供前端「點品種看它自己 K線」。
                              crop_map 為 identity。每日 series 存 avg/high(上價)/mid(中價,取 API「中價」量加權)/low(下價)/qty。
                              index 另存 latest_var[市場][作物][品種]=最新價，供比價分頁「品種細部」跨市場排序。
                              各市場僅出實際有交易者(葉菜市場只有葉菜、大市場整排水果+品種)。
                              --probe <市場> 可 dump 原始欄位(prices_probe.json)。latest 取最近 avg>0。
  fetch_cwa.py                抓 CWA 颱風/路徑潛勢/侵襲機率/雨量/氣溫 → typhoon_status.json；
                              並逐日「向前累積」真實天氣事件 → weather_events.json
                              （颱風/大雨≥80mm/低溫≤10°C，去重、保留 ~2 年，K線標記用）。
                              另抓 F-C0032-001（全國各縣市今明36小時）→ weather_forecast.json
                              ={counties:{縣市:{periods:[{label,pop,minT,maxT,wx}]}}}，供商人擺攤指數/
                              農夫農事建議。parse_nationwide_36h 大小寫/中英文欄位容錯、縣市名「臺→台」。
  fetch_yield.py              抓農業部「生產概況」(UnitId=113蔬菜/135果品，免金鑰) → yield_index.json
                              ={national:{作物:kg/ha}, counties:{縣市:{作物:kg/ha}}}。取最新年度、排除彙總列
                              (臺灣省/合計)、臺→台；欄名容錯(每公頃平均產量_公斤 有無後綴皆可)。前端 yieldInfo()
                              以所在縣市優先(÷10000→kg/㎡)、退全國、再退內建估算(YIELD_ALIAS 對照概況作物名)。
  build_advisory.py           田區登記表 + 天氣 → 決策模型 → harvest_advisory.json（含 EV、schedule）。
                              註：前端 index.html 另有自帶的 client 版決策，這支為後端/通知用。
  notify.py                   挑急迫田 → LINE Messaging API / webhook 推播（去重；未設則 dry-run）
  requirements.txt            requests
data/
  fields.example.json         田區登記表範例（真實檔為 data/fields.json，已 gitignore）
.github/workflows/
  update-data.yml             天氣/颱風每 30 分：fetch_cwa → build_advisory → notify → commit
                              (typhoon_status/weather_events/harvest_advisory/cwa_debug)。輕量、快。
  update-prices.yml           批發行情每日 08/13/17 時(台灣)：fetch_prices → commit
                              (prices_index/prices)。抓 2 年較慢(~15 分)，故與天氣拆開、互不阻塞。
  ci.yml                      PR 檢查：py_compile + 決策 demo + notify dry-run + 前端關鍵元素
（部署）                        採 GitHub 內建「Deploy from a branch: main」(pages-build-deployment
                              自動觸發)；不用 Actions 版 pages.yml（權限受限會失敗，已移除）。
.env.example                  CWA_API_KEY / LINE / webhook 範例
```

前端會讀取（不存在時退回 demo）：`prices_index.json` + `prices/NN.json`（行情，逐市場 lazy load）、
`typhoon_status.json`（颱風現況）、`weather_events.json`（K線天氣事件標記）、
`harvest_advisory.json`（後端決策），皆置於站台根。兩支排程都 push 到 main（Pages 服務分支），
push 前都有 fetch+rebase 重試，避免彼此/部署競爭 main 造成非快進被拒。

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

- **PHI 逐藥×逐作物實查**：`data/fields.example.json` 的 `phi_days` 為量級示意，PHI 是「該藥×該作物」
  的登記值（同種菜不同藥天數不同），**不可臆填、法規硬限制**。前端田區表單已改為讓農友自填＋附官方查詢
  連結（田邊好幫手 m.moa.gov.tw/Pesticide、防檢署 pesticide.aphia.gov.tw），不內建假 PHI 常數。
- **生育日數/產量係數已校準**：`GROWTH`(index.html)／`GROWTH_DAYS`(build_advisory.py)／`YIELD_M2` 已依
  農業部農業知識入口網·各區農改場·農情調查資料校準（snippet 來源、med 信心，gov 站 403 無法直讀原表，
  仍屬估算）。要更精準可改由農情調查開放資料(每公頃單產×縣市)動態帶入。`fetch_cwa.py` 各 `parse_*`
  的 CWA JSON 欄位路徑仍須以真實 API 回應校準。
- **雲林測站站號別寫死**：以 `O-A0001-001` / `C-B0074-002` 回應過濾雲林縣站點取當前有效站號。
- **作物批發名校準**：`fetch_prices.py` 的 `VEG_MAP`/`FRUIT_MAP` 批發名須與農業部「農產品交易行情」
  實際「作物名稱」相符。已知 `地瓜葉→甘藷葉` 全台回 0（名稱不符，前端不顯示），水果批發名
  （如 火龍果→紅龍果、芭樂→番石榴）多數可對到但仍應逐一核對；對不到者跳過即可、不影響其他品項。

## 本機測試

```bash
pip install -r scripts/requirements.txt
python3 scripts/build_advisory.py --fields data/fields.example.json --demo-typhoon   # 注入示範颱風
python3 scripts/fetch_cwa.py            # 需 CWA_API_KEY，否則寫 active=false
# 前端：直接開 index.html（無 JSON 會自動跑 demo）
```

## 分支慣例

- 開發分支：`claude/vegetable-harvest-weather-system-tjpqnj`
- 資料 JSON 由 `update-data.yml`（天氣，30 分）與 `update-prices.yml`（行情，每日數次）
  兩支排程分別提交到 Pages 所服務的 main 分支根（見 README 部署段）。
- 版本號在 `index.html` 的 `const VERSION`（頁尾顯示「農商雷達 vX.Y.Z」，淺灰置中）。
  上架前應用戶要求自 **`v1.0.0`** 重新起算，改用標準 SemVer `X.Y.Z`（前身「巡田水」曾用 v1~v2、
  改名後 v3.x，皆已重置為 1.0.0）。每次前端有感更新遞增，修 bug 進 Z、加功能進 Y、大改版進 X。
  刻意不用日期式版號，以免和右上「更新：<資料時間>」混淆。
