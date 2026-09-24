"""데모용 가짜 데이터로 전체 파이프라인을 돌려 docs/demo.json 생성.
실제 시세가 아닙니다. 화면 확인·분석 로직 테스트용."""
import pathlib
import sys

import numpy as np
import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import main  # noqa: E402

rng = np.random.default_rng(7)
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
us_days = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=380)
kr_days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=380)
n = len(us_days)

f = rng.normal(0, 4, n)                    # 미국 10년 일간 변화(bp) 공통 요인
f[-20:] = rng.normal(0, 6, 20)             # 최근 변동성 확대
f -= f.mean()                              # 수준이 비현실적으로 흘러가지 않게
g = rng.normal(0, 1, n)                    # 위험선호 요인


def rate(start, load, noise, days=us_days, lag=0, weekly=False):
    x = np.roll(f, lag) * load + rng.normal(0, noise, n)
    s = pd.Series(start + np.cumsum(x) / 100, index=days)
    return s.resample("W-THU").last() if weekly else s


def price(start, rate_beta_pct_per_bp, vol, risk=0.0, days=us_days, lag=0, flip_recent=False):
    b = np.full(n, rate_beta_pct_per_bp)
    if flip_recent:
        b[-20:] = -rate_beta_pct_per_bp        # 최근 20일 관계 역전(디커플링 데모)
    r = b * np.roll(f, lag) + risk * g + rng.normal(0, vol, n)
    return pd.Series(start * np.exp(np.cumsum(r) / 100), index=days)


raw = {
    "US10Y": rate(4.10, 1.0, 0.0),
    "US2Y": rate(3.60, 0.75, 3.5),
    "US30Y": rate(4.60, 0.9, 2.5),
    "US_MORT30": rate(6.30, 0.8, 2.0, weekly=True),
    "KR_BASE": pd.Series(2.50, index=kr_days),
    "KR3Y": rate(2.45, 0.35, 1.5, days=kr_days),
    "KR10Y": rate(2.85, 0.5, 1.5, days=kr_days),
    "USDKRW": price(1380, 0.04, 0.25, risk=-0.1),
    "JPYKRW": price(930, -0.03, 0.35),
    "DXY": price(100, 0.035, 0.35),
    "USDJPY": price(148, 0.07, 0.5),
    "USDCNH": price(7.15, 0.012, 0.2),
    "MOVE": price(95, 0.3, 3.0),
    "GOLD": price(2600, -0.2, 0.8, flip_recent=True),
    "TLT": price(90, -0.16, 0.2),
    "NASDAQ": price(18000, -0.06, 1.0, risk=0.8),
    "KOSPI": price(2600, -0.04, 0.9, risk=0.6, days=kr_days),
    "QQQ": price(480, -0.07, 1.0, risk=0.9), "MSFT": price(420, -0.06, 1.3, risk=0.7),
    "SOXX": price(220, -0.05, 1.9, risk=1.2), "NVDA": price(130, -0.04, 2.6, risk=1.3),
    "KBE": price(50, 0.06, 1.2, risk=0.5), "JPM": price(210, 0.04, 1.1, risk=0.4),
    "REM": price(22, -0.08, 1.0, risk=0.4), "AGNC": price(9.8, -0.09, 1.1, risk=0.4),
    "NLY": price(19.5, -0.08, 1.1, risk=0.4),
    "K_SW": price(9500, -0.05, 1.4, risk=0.6, days=kr_days),
    "NAVER": price(180000, -0.05, 1.6, risk=0.5, days=kr_days),
    "KAKAO": price(38000, -0.06, 1.8, risk=0.6, days=kr_days),
    "K_SEMI": price(38000, -0.02, 2.0, risk=1.0, days=kr_days),
    "SEC": price(60000, -0.015, 1.8, risk=0.9, days=kr_days),
    "HYNIX": price(190000, -0.02, 2.5, risk=1.1, days=kr_days),
    "K_BANK": price(11000, 0.12, 1.0, risk=0.4, days=kr_days, flip_recent=True),
    "KB": price(80000, 0.03, 1.3, risk=0.4, days=kr_days),
    "SHINHAN": price(52000, 0.025, 1.3, risk=0.4, days=kr_days),
    "K_REIT": price(4700, -0.04, 0.7, days=kr_days),
    "MKIF": price(12500, -0.035, 0.6, days=kr_days),
    "SLIFE": price(90000, 0.04, 1.4, risk=0.3, days=kr_days),
    "K_CONSTR": price(14000, -0.04, 1.4, risk=0.4, days=kr_days),
}
raw["US10Y_REAL"] = raw["US10Y"] * 0 + 1.85 + np.cumsum(f * 0.6 + rng.normal(0, 2, n)) / 100
raw["US10Y_BEI"] = raw["US10Y"] - raw["US10Y_REAL"]

now = pd.Timestamp.now(tz="UTC").isoformat()
demo_news = {
    "rates_fx": [{"title": f"[데모] 금리·환율 기사 제목 예시 {i+1}", "source": "데모", "link": "",
                  "published": now, "summary": "실제 기사가 아닌 화면 확인용 예시입니다.",
                  "tags": ["US10Y", "USDKRW"][: 1 + i % 2], "direction": ["up", "down", "none"][i % 3],
                  "importance": 3 - i % 3} for i in range(5)],
    "stocks": [{"title": f"[데모] 주식 기사 제목 예시 {i+1}", "source": "데모", "link": "",
                "published": now, "summary": "실제 기사가 아닌 화면 확인용 예시입니다.",
                "tags": ["SOXX", "K_BANK", "AGNC"][i % 3: i % 3 + 1], "direction": ["down", "up", "mixed"][i % 3],
                "importance": 2} for i in range(5)],
}
tl = [("US10Y", "미국 10년", "rate"), ("KR10Y", "국고채 10년", "rate"), ("USDKRW", "원/달러", "fx"),
      ("JPYKRW", "원/100엔", "fx"), ("QQQ", "미장 기술", "stock"), ("SOXX", "미장 반도체", "stock"),
      ("KBE", "미장 은행", "stock"), ("REM", "미장 모기지 리츠", "stock"), ("K_SW", "국장 기술", "stock"),
      ("K_SEMI", "국장 반도체", "stock"), ("K_BANK", "국장 은행", "stock"), ("K_REIT", "국장 리츠·인프라", "stock")]
dirs, confs = ["up", "flat", "down"], ["low", "mid", "high"]
demo_fc = {"generated_at": now, "model": "demo",
           "brief": ["[데모] 실제 전망이 아닌 화면 예시입니다", "Claude API 키를 넣으면 여기에 3줄 요약이 나옵니다",
                     "근거·무효화 조건·적중률이 함께 표시됩니다"],
           "items": [{"key": k, "label": lb, "cls": c, "horizon": h, "direction": dirs[(i + j) % 3],
                      "confidence": confs[(i * 2 + j) % 3],
                      "reasons": ["[데모] 근거 예시 1: 수치·상관·베타에서 인용", "[데모] 근거 예시 2: 뉴스 제목에서 인용"],
                      "invalidation": "[데모] 이 조건이 오면 전망 철회"}
                     for i, (k, lb, c) in enumerate(tl) for j, h in enumerate(["1W", "1M"])]}

main.run(False, raw=raw, warnings=["데모 데이터입니다 — 실제 시세가 아닙니다"],
         news_override=demo_news, forecast_override=demo_fc, out_path=ROOT / "docs" / "demo.json")
