"""실행 진입점.
  python src/main.py          # 시세·분석만 갱신(빠름, 장중 반복용)
  python src/main.py --full   # + 뉴스 수집·요약, 전망 생성(하루 2번 권장)
결과: docs/data.json (앱이 읽는 파일), docs/state/*.json (전망 기록·알림 상태)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import alerts  # noqa: E402
import analytics  # noqa: E402
import fetch  # noqa: E402
import forecast  # noqa: E402
import news as news_mod  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATE = DOCS / "state"


def _load(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save(p: pathlib.Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


def claude_client():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


def run(full: bool, raw=None, warnings=None, news_override=None, forecast_override=None, out_path=None):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if raw is None:
        raw, warnings = fetch.fetch_all(cfg)
    built, S = analytics.build(raw, cfg)
    prev = _load(out_path or DOCS / "data.json", {})
    today = dt.date.today().isoformat()

    # 뉴스·전망: --full일 때만 새로 만들고, 아니면 직전 것을 유지
    news, fc = prev.get("news", {"rates_fx": [], "stocks": []}), prev.get("forecast")
    log = _load(STATE / "forecast_log.json", [])
    if news_override is not None:
        news, fc = news_override, forecast_override
    elif full:
        news = news_mod.collect(cfg.get("news", {}))
        client = claude_client()
        if client:
            model = cfg.get("anthropic_model", "claude-sonnet-5")
            news = news_mod.enrich(news, client, model, list(built["series"].keys()))
            _, rates = forecast.score(log, S)
            new_fc = forecast.make(built, news, cfg, client, model, rates)
            if new_fc:
                fc = new_fc
                log = forecast.log_forecast(log, fc, S)
        else:
            fc = None
    log, hit_rates = forecast.score(log, S)
    if news_override is None:
        _save(STATE / "forecast_log.json", log)

    brief = (fc or {}).get("brief") or forecast.rule_brief(built)
    found = alerts.detect(built, cfg.get("alerts", {}))
    if news_override is None:
        _save(STATE / "alert_state.json", alerts.send(found, _load(STATE / "alert_state.json", {}), today))

    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "news_updated_at": dt.datetime.now(dt.timezone.utc).isoformat() if full else prev.get("news_updated_at"),
        "is_demo": news_override is not None,
        **built,
        "brief": brief, "brief_source": "claude" if (fc and fc.get("brief")) else "rule",
        "news": news, "forecast": fc, "hit_rates": hit_rates,
        "recent_scored": [e for e in log if e["result"]][-30:],
        "alerts": found, "calendar": [c for c in cfg.get("calendar", []) if str(c["date"]) >= today],
        "warnings": warnings or [],
    }
    _save(out_path or DOCS / "data.json", data)
    print(f"[ok] {len(built['series'])}개 시계열, 경고 {len(warnings or [])}건 → {out_path or DOCS / 'data.json'}")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="뉴스·전망까지 갱신")
    run(ap.parse_args().full)
