"""전망: Claude가 데이터·뉴스를 근거로 구조화된 전망을 내고, 모든 전망을 기록해 나중에 채점합니다."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from news import _ask_json

HORIZON_DAYS = {"1W": 7, "1M": 30}
# '보합'으로 볼 범위 (이보다 작게 움직이면 flat)
FLAT_BAND = {"rate": {"1W": 5, "1M": 10},      # bp
             "fx": {"1W": 0.5, "1M": 1.0},     # %
             "stock": {"1W": 1.0, "1M": 3.0}}  # %


def targets(cfg: dict, series: dict) -> list[dict]:
    t = [{"key": "US10Y", "label": "미국 10년", "cls": "rate"},
         {"key": "KR10Y", "label": "국고채 10년", "cls": "rate"},
         {"key": "USDKRW", "label": "원/달러", "cls": "fx"},
         {"key": "JPYKRW", "label": "원/100엔", "cls": "fx"}]
    for mkt, lst in (cfg.get("sectors") or {}).items():
        for s in lst:
            t.append({"key": s["etf"], "label": f"{'미장' if mkt == 'US' else '국장'} {s['sector']}", "cls": "stock"})
    return [x for x in t if x["key"] in series]


SYSTEM = """당신은 신중한 매크로 애널리스트입니다. 아래 데이터(수치, 상관·베타, 뉴스 제목)만 근거로
금리·환율·섹터의 1주(1W)와 1개월(1M) 방향을 전망합니다.
원칙:
- 단기 방향 예측의 적중률은 원래 낮습니다. 근거가 약하면 confidence를 low로, 방향을 flat으로 두세요.
- 근거는 입력 데이터에 있는 수치·관계·뉴스만 인용하세요. 입력에 없는 사실(발표 수치, 인물 발언 등)을 지어내지 마세요.
- 각 전망에 '이 조건이 오면 전망이 틀린 것'인 무효화 조건을 적으세요.
- 과거 적중률(hit_rates)이 낮은 대상은 더 보수적으로 판단하세요.
출력은 JSON 하나만(설명·코드펜스 금지):
{"brief": ["오늘 시장 요약 3줄, 각 60자 이내"],
 "items": [{"key": "대상 키", "horizon": "1W|1M", "direction": "up|flat|down",
            "confidence": "low|mid|high", "reasons": ["근거 2~3개, 각 60자 이내"],
            "invalidation": "무효화 조건 1개"}]}
items는 모든 대상 × 두 기간을 빠짐없이 포함하세요."""


def _compact(built: dict, news: dict, cfg: dict, hit_rates: dict, tlist: list[dict]) -> str:
    ser = built["series"]
    keys = {t["key"] for t in tlist} | {"US2Y", "US10Y_REAL", "US10Y_BEI", "US_2S10S", "USKR_10Y",
                                         "DXY", "USDJPY", "USDCNH", "MOVE", "KR_BASE", "KR3Y", "MORT_SPREAD"}
    snap = {k: {"name": ser[k]["name"], "last": ser[k]["last"], "date": ser[k]["last_date"],
                "chg": ser[k]["chg"], "unit": ser[k]["kind"]} for k in keys if k in ser}
    cp = {a: [{k: r[k] for k in ("name", "rho_s", "rho_l", "status")} for r in rows[:12]]
          for a, rows in built["coupling"].items()}
    betas = {s["etf"]: {i["key"]: i["beta_us"] for i in s["items"]}
             for lst in built["sectors"].values() for s in lst}
    nw = {g: [{"title": x["title"], "summary": x.get("summary", ""), "tags": x.get("tags", [])}
              for x in items[:12]] for g, items in news.items()}
    return json.dumps({
        "today": dt.date.today().isoformat(),
        "targets": [{"key": t["key"], "label": t["label"]} for t in tlist],
        "snapshot": snap, "us10y_decomposition": built.get("decomposition"),
        "coupling": cp, "beta_per_10bp_us10y": betas, "scenario": built.get("scenario"),
        "news": nw, "calendar": cfg.get("calendar", []), "hit_rates": hit_rates,
    }, ensure_ascii=False, default=str)


def make(built: dict, news: dict, cfg: dict, client, model: str, hit_rates: dict) -> dict | None:
    tlist = targets(cfg, built["series"])
    try:
        res = _ask_json(client, model, SYSTEM, _compact(built, news, cfg, hit_rates, tlist), max_tokens=6000)
    except Exception as e:  # noqa: BLE001
        print(f"[forecast] 실패: {e}")
        return None
    labels = {t["key"]: t for t in tlist}
    items = [dict(i, label=labels[i["key"]]["label"], cls=labels[i["key"]]["cls"])
             for i in res.get("items", []) if i.get("key") in labels and i.get("horizon") in HORIZON_DAYS]
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "brief": res.get("brief", [])[:3], "items": items, "model": model}


# ── 기록 & 채점 ──────────────────────────────────────────
def _move(cls: str, base: float, now: float) -> float:
    return (now - base) * 100 if cls == "rate" else (now / base - 1) * 100


def log_forecast(log: list[dict], fc: dict, S: dict) -> list[dict]:
    today = dt.date.today().isoformat()
    for it in fc["items"]:
        s = S[it["key"]]["s"]
        entry = {"made": today, "key": it["key"], "label": it["label"], "cls": it["cls"],
                 "horizon": it["horizon"], "direction": it["direction"], "confidence": it.get("confidence"),
                 "base": float(s.iloc[-1]), "base_date": s.index[-1].strftime("%Y-%m-%d"),
                 "due": (s.index[-1] + pd.Timedelta(days=HORIZON_DAYS[it["horizon"]])).strftime("%Y-%m-%d"),
                 "result": None}
        # 같은 날 같은 대상·기간은 마지막 것만 남김
        log = [e for e in log if not (e["made"] == today and e["key"] == it["key"]
                                      and e["horizon"] == it["horizon"] and e["result"] is None)]
        log.append(entry)
    return log[-3000:]


def score(log: list[dict], S: dict) -> tuple[list[dict], dict]:
    for e in log:
        if e["result"] is not None or e["key"] not in S:
            continue
        s = S[e["key"]]["s"]
        due = pd.Timestamp(e["due"])
        if s.index[-1] < due:
            continue
        now = float(s.asof(due))
        mv = _move(e["cls"], e["base"], now)
        band = FLAT_BAND[e["cls"]][e["horizon"]]
        actual = "up" if mv > band else "down" if mv < -band else "flat"
        e["result"] = {"move": round(mv, 2), "actual": actual, "hit": actual == e["direction"]}

    rates: dict = {}
    done = [e for e in log if e["result"]]
    for e in done:
        for k in (e["key"], "_all", f"_conf_{e.get('confidence')}"):
            r = rates.setdefault(k, {"n": 0, "hit": 0})
            r["n"] += 1
            r["hit"] += int(e["result"]["hit"])
    for r in rates.values():
        r["rate"] = round(r["hit"] / r["n"], 3) if r["n"] else None
    return log, rates


def rule_brief(built: dict) -> list[str]:
    """Claude 키가 없을 때 쓰는 규칙 기반 요약(전망 아님)."""
    ser, out = built["series"], []
    u = ser.get("US10Y")
    d = built.get("decomposition")
    if u and u["chg"]["d1"] is not None:
        driver = ""
        if d and d["w1"]["real"] is not None and d["w1"]["bei"] is not None:
            driver = " · 1주 변화는 " + ("실질금리 주도" if abs(d["w1"]["real"]) >= abs(d["w1"]["bei"]) else "기대인플레 주도")
        out.append(f"미국 10년 {u['last']:.2f}% ({u['chg']['d1']:+.1f}bp){driver}")
    fx = ser.get("USDKRW")
    if fx and fx["chg"]["d1"] is not None:
        out.append(f"원/달러 {fx['last']:,.1f}원 ({fx['chg']['d1']:+.2f}%)")
    dec = [r["name"] for r in built["coupling"].get("US10Y", []) if r["status"].startswith("decoupled")]
    out.append(f"미국 10년과 평소 관계가 깨진 지표: {', '.join(dec[:3])}" if dec else "미국 10년과의 평소 관계는 대체로 유지 중")
    return out
