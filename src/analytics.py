"""분석 엔진: 스냅샷, 커플링/디커플링, 금리 베타, 시나리오, 10년물 분해."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ── 기본 도구 ─────────────────────────────────────────────
def changes(s: pd.Series, kind: str) -> pd.Series:
    """상관·베타는 '수준'이 아니라 '변화'로 계산합니다(수준끼리는 허위상관이 생김).
    rate(%) → bp 변화, spread(bp) → bp 변화, price → 로그수익률(%)."""
    s = s.dropna()
    if kind == "rate":
        return (s.diff() * 100).dropna()
    if kind == "spread":
        return s.diff().dropna()
    return (np.log(s).diff() * 100).dropna()


def align(x: pd.Series, xs: str, y: pd.Series, ys: str) -> pd.DataFrame:
    """두 변화 시계열을 날짜로 맞춤.
    세션이 다르면 한국 t일을 미국 t-1일(직전 미국 종가)과 짝지음:
    한국장은 전날 밤 미국장의 움직임에 반응하기 때문."""
    if xs == ys:
        return pd.concat([x.rename("x"), y.rename("y")], axis=1, join="inner").dropna()
    kr, us, kr_is_x = (x, y, True) if xs == "KR" else (y, x, False)
    left = kr.rename("kr").rename_axis("d").reset_index()
    right = us.rename("us").rename_axis("d").reset_index()
    m = pd.merge_asof(left.sort_values("d"), right.sort_values("d"), on="d",
                      allow_exact_matches=False, direction="backward",
                      tolerance=pd.Timedelta(days=5)).dropna()
    m = m.drop_duplicates(subset="us", keep="first")  # 연휴 뒤 같은 미국일에 여러 번 붙는 것 방지
    m = m.set_index("d")
    return pd.DataFrame({"x": m["kr"] if kr_is_x else m["us"],
                         "y": m["us"] if kr_is_x else m["kr"]})


def _corr(df: pd.DataFrame) -> float | None:
    if len(df) < 10 or df["x"].std() == 0 or df["y"].std() == 0:
        return None
    return float(df["x"].corr(df["y"]))


def _r(v, n=3):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), n)


# ── 스냅샷 ────────────────────────────────────────────────
def snapshot(s: pd.Series, kind: str, n_hist: int) -> dict:
    s = s.dropna()
    last_d, last = s.index[-1], float(s.iloc[-1])

    def delta(ref):
        if ref is None or (isinstance(ref, float) and math.isnan(ref)):
            return None
        if kind == "rate":
            return (last - ref) * 100
        if kind == "spread":
            return last - ref
        return (last / ref - 1) * 100

    prev = float(s.iloc[-2]) if len(s) > 1 else None
    w = s.asof(last_d - pd.Timedelta(days=7))
    m = s.asof(last_d - pd.Timedelta(days=30))
    h = s.iloc[-n_hist:]
    return {
        "last": _r(last, 4), "last_date": last_d.strftime("%Y-%m-%d"),
        "chg": {"d1": _r(delta(prev), 3), "w1": _r(delta(w), 3), "m1": _r(delta(m), 3)},
        "hist": [[d.strftime("%Y-%m-%d"), _r(v, 4)] for d, v in h.items()],
    }


# ── 본체 ─────────────────────────────────────────────────
def build(raw: dict[str, pd.Series], cfg: dict) -> tuple[dict, dict]:
    meta = cfg["series"]
    S: dict[str, dict] = {}
    for k, m in meta.items():
        if k in raw and len(raw[k].dropna()) > 2:
            S[k] = {"s": raw[k].dropna(), "kind": m.get("kind", "price"),
                    "session": m.get("session", "US"), "name": m["name"],
                    "group": m.get("group", ""), "digits": m.get("digits", 2)}
    for k, m in (cfg.get("derived") or {}).items():
        if m["a"] in S and m["b"] in S:
            a, b = S[m["a"]]["s"], S[m["b"]]["s"]
            b = b.reindex(b.index.union(a.index)).ffill().reindex(a.index)
            d = ((a - b) * 100).dropna()
            if len(d) > 2:
                S[k] = {"s": d, "kind": "spread", "session": S[m["a"]]["session"],
                        "name": m["name"], "group": "spread", "digits": 0}

    C = {k: changes(v["s"], v["kind"]) for k, v in S.items()}
    n_hist = int(cfg.get("history_points", 260))
    Ls, Ll = int(cfg.get("corr_short", 20)), int(cfg.get("corr_long", 120))
    thr = float(cfg.get("couple_threshold", 0.3))
    bw = int(cfg.get("beta_window", 60))

    series_out = {}
    for k, v in S.items():
        snap = snapshot(v["s"], v["kind"], n_hist)
        snap.update(name=v["name"], kind=v["kind"], session=v["session"],
                    group=v["group"], digits=v["digits"])
        series_out[k] = snap

    # 커플링/디커플링
    def coupling(anchor: str, cands: list[str]) -> list[dict]:
        if anchor not in C:
            return []
        rows = []
        for k in cands:
            if k not in C or k == anchor:
                continue
            df = align(C[anchor], S[anchor]["session"], C[k], S[k]["session"])
            # 기준(평소) 구간은 최근 구간과 겹치지 않게: 최근 변화가 기준을 오염시키지 않도록
            rl, rs = _corr(df.iloc[-Ll:-Ls]), _corr(df.iloc[-Ls:])
            if rl is None or rs is None:
                continue
            if abs(rl) < thr:
                status = "new_coupling" if abs(rs) >= max(0.5, thr + 0.2) else "weak"
            elif np.sign(rs) != np.sign(rl) and abs(rs) >= 0.15:
                status = "decoupled_flip"
            elif abs(rs) < 0.5 * abs(rl):
                status = "decoupled_fade"
            else:
                status = "coupled"
            rows.append({"key": k, "name": S[k]["name"], "rho_s": _r(rs, 2), "rho_l": _r(rl, 2),
                         "status": status, "lagged": S[k]["session"] != S[anchor]["session"]})
        order = {"decoupled_flip": 0, "decoupled_fade": 1, "new_coupling": 2, "coupled": 3, "weak": 4}
        rows.sort(key=lambda r: (order[r["status"]], -abs(r["rho_l"])))
        return rows

    cc = cfg.get("coupling_candidates", {})
    coupling_out = {a: coupling(a, c) for a, c in cc.items()}

    # 금리 베타: "앵커 +10bp일 때 이 자산은 몇 % (또는 bp)"
    def beta(anchor: str, k: str) -> dict | None:
        if anchor not in C or k not in C:
            return None
        df = align(C[anchor], S[anchor]["session"], C[k], S[k]["session"]).iloc[-bw:]
        if len(df) < 30 or df["x"].var() == 0:
            return None
        b = df["x"].cov(df["y"]) / df["x"].var()
        r = df["x"].corr(df["y"])
        return {"per10": _r(b * 10, 2), "r2": _r(r * r, 2), "n": len(df)}

    def item(k: str) -> dict | None:
        if k not in series_out:
            return None
        return {"key": k, "beta_us": beta("US10Y", k),
                "beta_kr": beta("KR10Y", k) if S[k]["session"] == "KR" else None}

    sectors_out = {}
    for mkt, lst in (cfg.get("sectors") or {}).items():
        sectors_out[mkt] = []
        for sec in lst:
            keys = [sec["etf"]] + list(sec.get("stocks", []))
            sectors_out[mkt].append({
                "sector": sec["sector"], "etf": sec["etf"],
                "items": [x for x in (item(k) for k in keys) if x],
                "extras": [e for e in sec.get("extras", []) if e in series_out],
            })

    krs = [{**item(x["key"]), "note": x.get("note", "")}
           for x in cfg.get("kr_rate_stocks", []) if item(x["key"])]

    # 시나리오: 미국 10년 ±N bp → 베타로 기계적 추정
    shock = float(cfg.get("scenario_bp", 20))
    scen_keys = ["KR10Y", "USDKRW", "JPYKRW"] + [s["etf"] for lst in (cfg.get("sectors") or {}).values() for s in lst]
    scen = []
    for k in scen_keys:
        b = beta("US10Y", k)
        if b and b["per10"] is not None:
            unit = "bp" if S[k]["kind"] in ("rate", "spread") else "%"
            scen.append({"key": k, "name": S[k]["name"], "unit": unit,
                         "up": _r(b["per10"] * shock / 10, 2), "down": _r(-b["per10"] * shock / 10, 2),
                         "r2": b["r2"]})

    # 미국 10년 분해: 명목 = 실질 + 기대인플레
    decomp = None
    if all(k in S for k in ("US10Y", "US10Y_REAL", "US10Y_BEI")):
        df = pd.concat([S["US10Y"]["s"], S["US10Y_REAL"]["s"], S["US10Y_BEI"]["s"]],
                       axis=1, keys=["n", "r", "b"], join="inner").dropna()
        if len(df) > 25:
            last = df.iloc[-1]

            def dchg(days):
                ref = df.asof(df.index[-1] - pd.Timedelta(days=days))
                return {"nominal": _r((last.n - ref.n) * 100, 1), "real": _r((last.r - ref.r) * 100, 1),
                        "bei": _r((last.b - ref.b) * 100, 1)}

            decomp = {"date": df.index[-1].strftime("%Y-%m-%d"), "nominal": _r(last.n, 3),
                      "real": _r(last.r, 3), "bei": _r(last.b, 3), "w1": dchg(7), "m1": dchg(30)}

    out = {"series": series_out, "coupling": coupling_out, "sectors": sectors_out,
           "kr_rate_stocks": krs, "scenario": {"shock_bp": shock, "rows": scen},
           "decomposition": decomp, "home_tiles": [k for k in cfg.get("home_tiles", []) if k in series_out]}
    return out, S
