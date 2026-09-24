"""데이터 수집: FRED(미국 금리), 한국은행 ECOS(한국 금리), Yahoo Finance(환율·주식)."""
from __future__ import annotations

import datetime as dt
import io
import os

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (rate-monitor)"}


def _clean_index(s: pd.Series) -> pd.Series:
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")]
    return s.sort_index().dropna()


def fred(series_id: str, start: dt.date) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start:%Y-%m-%d}"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(pd.to_numeric(df[series_id], errors="coerce").values, index=df[df.columns[0]])
    return _clean_index(s)


def ecos(key: str, stat: str, item: str, start: dt.date, end: dt.date) -> pd.Series:
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/"
           f"{stat}/D/{start:%Y%m%d}/{end:%Y%m%d}/{item}")
    j = requests.get(url, headers=UA, timeout=30).json()
    rows = j.get("StatisticSearch", {}).get("row", [])
    if not rows:
        raise RuntimeError(f"ECOS 응답 없음 ({stat}/{item}): {j.get('RESULT', j)}")
    s = pd.Series({r["TIME"]: float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE") not in (None, "")})
    s.index = pd.to_datetime(s.index, format="%Y%m%d")
    return _clean_index(s)


def yahoo(tickers: list[str], start: dt.date) -> dict[str, pd.Series]:
    import yfinance as yf

    data = yf.download(tickers, start=start.isoformat(), interval="1d", auto_adjust=True,
                       progress=False, threads=True, group_by="column")
    if data is None or data.empty:
        return {}
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    out = {}
    for t in tickers:
        if t in close.columns:
            s = close[t].dropna()
            if len(s):
                out[t] = _clean_index(s.copy())
    return out


def fetch_all(cfg: dict) -> tuple[dict[str, pd.Series], list[str]]:
    """설정의 모든 시계열을 받아 {키: Series} 반환. 실패한 항목은 경고로 모아 둡니다."""
    end = dt.date.today()
    start = end - dt.timedelta(days=int(cfg.get("lookback_days", 540)))
    meta = cfg["series"]
    raw: dict[str, pd.Series] = {}
    warnings: list[str] = []

    # FRED
    for k, m in meta.items():
        if m["src"] != "fred":
            continue
        try:
            raw[k] = fred(m["id"], start)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{m['name']} 수집 실패(FRED): {e}")

    # ECOS
    key = os.environ.get("ECOS_API_KEY", "").strip()
    for k, m in meta.items():
        if m["src"] != "ecos":
            continue
        if not key:
            warnings.append(f"{m['name']}: ECOS_API_KEY가 없어 건너뜀")
            continue
        try:
            raw[k] = ecos(key, m["stat"], m["item"], start, end)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{m['name']} 수집 실패(ECOS): {e}")

    # Yahoo (+ 장중 미국 10년 ^TNX)
    ymap = {m["id"]: k for k, m in meta.items() if m["src"] == "yf"}
    live = {m["live"]: k for k, m in meta.items() if m.get("live")}
    try:
        got = yahoo(list(ymap) + list(live), start)
    except Exception as e:  # noqa: BLE001
        got = {}
        warnings.append(f"Yahoo 수집 실패: {e}")
    for t, k in ymap.items():
        if t in got:
            raw[k] = got[t] * float(meta[k].get("scale", 1))
        else:
            warnings.append(f"{meta[k]['name']}({t}) 데이터 없음")

    # FRED는 하루 늦으므로, ^TNX가 더 최신이면 마지막 값을 덧붙임
    for t, k in live.items():
        if t in got and k in raw and len(got[t]):
            tnx = got[t]
            tnx = tnx / 10 if tnx.iloc[-1] > 20 else tnx   # 과거 Yahoo 표기(×10) 대비
            newer = tnx[tnx.index > raw[k].index[-1]]
            if len(newer):
                raw[k] = pd.concat([raw[k], newer])
    return raw, warnings
