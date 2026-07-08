#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_advisory.py  ——  雲林葉菜「搶收決策」合成模型 v1

輸入：
  data/fields.json         田區登記表（見 data/fields.example.json 格式）
  typhoon_status.json      fetch_cwa.py 產出的颱風/雨量現況（可缺；缺則視為無颱風）

輸出：
  harvest_advisory.json    每田×每菜的決策物件陣列，供前端 index.html 搶收預判分頁讀取

v1 實作範圍（對齊設計文件）：
  B 硬約束閘門：PHI（安全採收期）、成熟度      ← 已實作
  D 時間軸求解：搶收窗 / deadline / partial      ← 已實作
  C 滅田風險 R：P×I×W×V 物理估                   ← 已實作（歷史類比校準留 v2 TODO）
  E 市場 EV 期望值                               ← v3 TODO（需接行情 base_price，先輸出 null）

用法：
  python3 scripts/build_advisory.py --fields data/fields.example.json --demo-typhoon
  python3 scripts/build_advisory.py --fields data/fields.json --typhoon typhoon_status.json
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))  # 台灣時間

# ─────────────── 可調參數（集中管理，對齊設計文件附表） ───────────────
SAFETY_BUFFER_H = 12          # 收工須在暴風到達前這麼多小時完成
MATURE_SOFT = 0.9             # 時間軸上視為「軟成熟」的門檻比例

# 生育日數 (夏作, 冬作)；夏作=5–10 月
GROWTH_DAYS = {
    "青江菜": (38, 48), "小白菜": (25, 38), "奶油白菜": (30, 40),
    "蚵白菜": (30, 40), "菠菜": (50, 50), "芥藍菜": (70, 70),
}
# 最低可搶收成熟度（低於此收了殘值過低）
MATURITY_MIN = {
    "青江菜": 0.75, "小白菜": 0.70, "奶油白菜": 0.72,
    "蚵白菜": 0.72, "菠菜": 0.75, "芥藍菜": 0.75,
}
# 作物脆弱度 V_crop（葉軟泡水即爛→高）
V_CROP = {
    "青江菜": 0.95, "小白菜": 0.95, "奶油白菜": 0.90,
    "蚵白菜": 0.90, "菠菜": 0.85, "芥藍菜": 0.80,
}
# 依淹水潛勢等級的「搶收提前量」小時（低窪田要更早收）
FLOOD_ADVANCE_H = {1: 0, 2: 0, 3: 12, 4: 18, 5: 24}

WIND_ANCHOR_MS = 45.0   # 風速正規化上限錨點
RAIN_ANCHOR_MM = 350.0  # 24hr 雨量正規化上限錨點


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def is_summer(d: datetime) -> bool:
    return 5 <= d.month <= 10


def growth_days(crop: str, plant_dt: datetime) -> int:
    summer, winter = GROWTH_DAYS.get(crop, (35, 45))
    return summer if is_summer(plant_dt) else winter


def parse_date(s: str) -> datetime:
    """接受 'YYYY-MM-DD' 或含時間的 ISO 字串，回傳 +08:00 datetime。"""
    if not s:
        return None
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(TZ)
        y, m, d = (int(x) for x in s.split("-"))
        return datetime(y, m, d, tzinfo=TZ)
    except Exception:
        return None


# ─────────────── B. 硬約束閘門 ───────────────
def phi_gate(field, now):
    """回傳 (phi_ok_dt, days_short, chemical)。days_short>0 表示 PHI 未到。"""
    chems = field.get("chemicals", []) or []
    latest = None
    latest_chem = None
    for c in chems:
        sd = parse_date(c.get("spray_date"))
        phi = c.get("phi_days")
        if sd is None or phi is None:
            continue
        expiry = sd + timedelta(days=int(phi))
        if latest is None or expiry > latest:
            latest = expiry
            latest_chem = c.get("name", "?")
    if latest is None:
        return None, 0, None
    days_short = math.ceil((latest - now).total_seconds() / 86400)
    return latest, max(0, days_short), latest_chem


def maturity_of(field, now):
    plant = parse_date(field.get("planting_date"))
    if plant is None:
        return None, None
    T = growth_days(field["crop"], plant)
    mat = (now - plant).total_seconds() / 86400 / T
    return round(mat, 3), T


# ─────────────── C. 滅田風險 R ───────────────
def risk_score(field, typhoon):
    if not typhoon or not typhoon.get("active"):
        return 0, {}
    p_arrival = float(typhoon.get("invade_prob") or 0.0)
    rain = float(typhoon.get("rain_24h_mm") or 0.0)
    gust = typhoon.get("forecast_gust_ms")
    rain_norm = clamp(rain / RAIN_ANCHOR_MM, 0, 1)
    if gust is not None:
        wind_norm = clamp(float(gust) / WIND_ANCHOR_MS, 0, 1)
        i_norm = clamp(0.5 * wind_norm + 0.5 * rain_norm, 0, 1)
    else:
        i_norm = rain_norm  # TODO v2: 併入陣風預測 F-C0034-005
    flood = int(field.get("flood_potential_level") or 1)
    elev = float(field.get("elevation_m") or 8)
    w_terrain = clamp(1.0 + 0.10 * (flood - 1) - 0.05 * clamp((elev - 5) / 10, -1, 1), 0.3, 1.3)
    v_crop = V_CROP.get(field["crop"], 0.9)
    r_raw = 100 * p_arrival * i_norm * w_terrain * v_crop
    # TODO v2: analog_loss_rate 歷史類比校準 calibrate(r_raw, analog, n)
    r = round(clamp(r_raw, 0, 100))
    return r, {
        "P_arrival": round(p_arrival, 2), "I_norm": round(i_norm, 2),
        "W_terrain": round(w_terrain, 2), "V_crop": v_crop, "R_raw": round(r_raw),
    }


# ─────────────── D. 時間軸求解 ───────────────
def solve_timeline(field, typhoon, now):
    """回傳 dict：harvest_deadline / slack_h / partial_pct / t_impact_safe。"""
    if not typhoon or not typhoon.get("active"):
        return {"deadline": None, "slack_h": None, "partial_pct": None, "t_safe": None}
    arrival = parse_date(typhoon.get("eta_iso"))
    if arrival is None:
        return {"deadline": None, "slack_h": None, "partial_pct": None, "t_safe": None}
    flood = int(field.get("flood_potential_level") or 1)
    advance_h = FLOOD_ADVANCE_H.get(flood, 0)
    t_safe = arrival - timedelta(hours=SAFETY_BUFFER_H + advance_h)
    dur_h = (field.get("area_ha", 0.5) * field.get("labor_h_per_ha", 60)
             / max(1, field.get("crew_size", 3)))
    deadline = t_safe - timedelta(hours=dur_h)
    slack_h = (deadline - now).total_seconds() / 3600
    # partial：暴風前的可作業時間裝不下所需工時
    avail_h = (t_safe - now).total_seconds() / 3600
    partial = None
    if dur_h > avail_h and avail_h > 0:
        partial = int(round(avail_h / dur_h * 100))
    return {"deadline": deadline, "slack_h": slack_h, "partial_pct": partial,
            "t_safe": t_safe, "dur_h": dur_h}


# ─────────────── A. 決策合成 ───────────────
def decide(field, typhoon, now):
    crop = field["crop"]
    mat, T = maturity_of(field, now)
    phi_ok, days_short, phi_chem = phi_gate(field, now)
    R, rb = risk_score(field, typhoon)
    tl = solve_timeline(field, typhoon, now)

    reasons = []
    immature = mat is not None and mat < MATURITY_MIN.get(crop, 0.75)
    dilemma = None

    # 決策分級（依 R 與 slack）
    slack_h = tl["slack_h"]
    if R >= 65 and slack_h is not None and slack_h <= (tl.get("dur_h", 6) * 1.2 + SAFETY_BUFFER_H):
        decision = "HARVEST_NOW"
    elif R >= 50:
        decision = "HARVEST_ADVISED"
    elif R >= 25:
        decision = "WATCH"
    else:
        decision = "NORMAL"

    # 成熟度閘門：未熟則最多觀望（收了殘值過低）
    if immature and decision in ("HARVEST_NOW", "HARVEST_ADVISED"):
        decision = "WATCH"
        reasons.append(f"成熟度僅 {round(mat*100)}%，未達 {round(MATURITY_MIN.get(crop,0.75)*100)}%，搶收殘值過低")

    # 理由：風險 / 淹水 / 時間窗
    if typhoon and typhoon.get("active"):
        reasons.insert(0, f"雲林暴風圈侵襲機率 {round(rb.get('P_arrival',0)*100)}%，"
                          f"預估 24hr 雨量 {typhoon.get('rain_24h_mm','?')}mm，滅田風險 {R}/100")
    flood = int(field.get("flood_potential_level") or 1)
    if flood >= 3:
        reasons.append(f"淹水潛勢等級 {flood}（{'低窪' if flood>=4 else '偏低'}），泡水 48hr 起爛根，需提前搶收")
    if crop == "芥藍菜":
        reasons.append("中長期作物（60–80 天），颱風曝險期最長")

    # 時間窗理由 + partial
    if tl["deadline"] is not None and decision in ("HARVEST_NOW", "HARVEST_ADVISED"):
        dl = tl["deadline"]
        reasons.append(f"最晚 {dl.month}/{dl.day} {dl.hour:02d}:{dl.minute:02d} 前須開始搶收")
    if tl["partial_pct"] is not None:
        reasons.append(f"暴風前可作業時間不足，人手僅能收約 {tl['partial_pct']}% 面積 → 依風險先收")

    # PHI 硬約束（一票否決不上市）。「兩難」物件只在颱風逼近、真的有搶收壓力時才觸發，
    # 以免無颱風時前端跳出「不收會泡水滅田」的誤導性警示。
    typhoon_active = bool(typhoon and typhoon.get("active"))
    if days_short > 0:
        reasons.append(f"⚠ 不可上市：距安全採收期還差 {days_short} 天（{phi_chem}）")
        if typhoon_active and decision in ("HARVEST_NOW", "HARVEST_ADVISED", "WATCH"):
            dilemma = {"days_short": days_short, "chemical": phi_chem}
            if R >= 50:
                reasons.append("兩難：現在收→農藥殘留超標恐遭銷毀；不收→泡水滅田。"
                               "建議加強排水保田或申報天災救助")
    elif phi_ok is not None:
        reasons.append("PHI 已過，可合法上市")

    if decision == "NORMAL" and not reasons:
        reasons.append("無迫近颱風時窗、風險分數低，按原計畫管理")

    # 信心度（v1 啟發式；forecast_spread/analog 待 v2）
    conf = 0.6
    if typhoon and typhoon.get("active"):
        conf += 0.1
    if all(field.get(k) is not None for k in ("planting_date", "flood_potential_level")):
        conf += 0.1
    if field.get("chemicals"):
        conf += 0.1
    conf = round(clamp(conf, 0.35, 0.95), 2)

    return {
        "field_id": field["field_id"],
        "crop": crop,
        "decision": decision,
        "confidence": conf,
        "risk_score": R,
        "maturity": mat,
        "flood_potential_level": field.get("flood_potential_level"),
        "harvest_deadline": tl["deadline"].isoformat() if tl["deadline"] else None,
        "dilemma": dilemma,
        "partial_pct": tl["partial_pct"],
        "immature": immature,
        "ev": None,  # TODO v3：接行情 base_price 做早收 vs 賭一把 EV 試算
        "risk_breakdown": rb,
        "reasons": reasons,
    }


def demo_typhoon(now):
    """--demo-typhoon 用：注入一個逼近中的颱風，供離線測試。"""
    eta = now + timedelta(hours=40)
    return {
        "active": True, "name": "克蘿莎 KROSA", "warning": "海上陸上颱風警報中",
        "invade_prob": 0.70, "eta_iso": eta.isoformat(),
        "eta_text": "約 40 小時後", "rain_24h_mm": 300, "forecast_gust_ms": 40,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", default="data/fields.json")
    ap.add_argument("--typhoon", default="typhoon_status.json")
    ap.add_argument("--demo-typhoon", action="store_true",
                    help="無 typhoon_status.json 時注入示範颱風")
    ap.add_argument("--out", default="harvest_advisory.json")
    args = ap.parse_args()

    now = datetime.now(TZ)

    with open(args.fields, encoding="utf-8") as f:
        reg = json.load(f)
    fields = reg.get("fields", reg if isinstance(reg, list) else [])

    typhoon = None
    if os.path.exists(args.typhoon):
        with open(args.typhoon, encoding="utf-8") as f:
            typhoon = json.load(f)
    elif args.demo_typhoon:
        typhoon = demo_typhoon(now)

    advisories = [decide(fd, typhoon, now) for fd in fields]

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "typhoon": {
            "name": (typhoon or {}).get("name"),
            "warning": (typhoon or {}).get("warning"),
            "invade_prob": (typhoon or {}).get("invade_prob"),
            "eta_text": (typhoon or {}).get("eta_text"),
            "rain_24h_mm": (typhoon or {}).get("rain_24h_mm"),
            "active": bool(typhoon and typhoon.get("active")),
        },
        "fields": advisories,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    active = out["typhoon"]["active"]
    print(f"[build_advisory] 寫出 {args.out}：{len(advisories)} 塊田，"
          f"颱風={'有' if active else '無'}")
    for a in advisories:
        print(f"  {a['field_id']:<8} {a['crop']:<5} {a['decision']:<16} "
              f"R={a['risk_score']:>3}  {'⚠PHI' if a['dilemma'] else ''}")


if __name__ == "__main__":
    main()
