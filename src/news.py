"""뉴스: Google News RSS 수집 → 중복 제거 → (선택) Claude로 요약·태그·방향."""
from __future__ import annotations

import calendar
import datetime as dt
import difflib
import json
import re
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (rate-monitor)"}


def _rss_url(q: str, lang: str) -> str:
    qq = urllib.parse.quote(f"{q} when:2d")
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={qq}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={qq}&hl=en-US&gl=US&ceid=US:en"


def _norm(t: str) -> str:
    return re.sub(r"[\W_]+", "", t.lower())


def collect(cfg_news: dict) -> dict[str, list[dict]]:
    import feedparser

    now = dt.datetime.now(dt.timezone.utc)
    max_age = dt.timedelta(hours=int(cfg_news.get("max_age_hours", 48)))
    limit = int(cfg_news.get("max_per_group", 25))
    out = {}
    for group in ("rates_fx", "stocks"):
        items: list[dict] = []
        for lang, queries in (cfg_news.get(group) or {}).items():
            for q in queries:
                try:
                    r = requests.get(_rss_url(q, lang), headers=UA, timeout=20)
                    feed = feedparser.parse(r.content)
                except Exception:  # noqa: BLE001
                    continue
                for e in feed.entries[:15]:
                    title = e.get("title", "")
                    source = (e.get("source") or {}).get("title", "")
                    if source and title.endswith(" - " + source):
                        title = title[: -len(source) - 3]
                    ts = e.get("published_parsed")
                    pub = dt.datetime.fromtimestamp(calendar.timegm(ts), dt.timezone.utc) if ts else now
                    if now - pub > max_age:
                        continue
                    items.append({"title": title.strip(), "source": source, "link": e.get("link", ""),
                                  "published": pub.isoformat(), "lang": lang, "query": q})
        # 중복 제거: 제목 유사도 0.8 이상이면 같은 기사로 봄
        items.sort(key=lambda x: x["published"], reverse=True)
        kept: list[dict] = []
        for it in items:
            n = _norm(it["title"])
            if any(difflib.SequenceMatcher(None, n, _norm(k["title"])).ratio() > 0.8 for k in kept):
                continue
            kept.append(it)
        out[group] = kept[:limit]
    return out


ENRICH_SYSTEM = """당신은 금리·환율·주식 뉴스를 분류하는 분석 보조입니다.
입력은 뉴스 제목 목록(JSON)입니다. 제목만 근거로 판단하고, 제목에 없는 사실은 만들지 마세요.
각 항목에 대해 다음을 JSON 배열로만 출력하세요(설명·코드펜스 금지):
[{"id": 번호, "summary": "한국어 한 줄 요약(40자 이내, 제목을 그대로 베끼지 말 것)",
  "tags": ["영향 지표 키 1~3개"], "direction": "up|down|mixed|none", "importance": 1~3}]
tags는 다음 키 중에서만 고르세요: {keys}
direction은 해당 태그 지표에 대한 제목상의 방향(상승 압력=up)입니다. 불분명하면 none."""


def _ask_json(client, model: str, system: str, user: str, max_tokens: int = 4000):
    msg = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    text = re.sub(r"```(?:json)?", "", text).strip()
    return json.loads(text)


def enrich(news: dict[str, list[dict]], client, model: str, keys: list[str]) -> dict[str, list[dict]]:
    """Claude로 요약·태그·방향·중요도 부여. 실패하면 원본 그대로 반환."""
    for group, items in news.items():
        if not items:
            continue
        payload = [{"id": i, "title": it["title"], "source": it["source"]} for i, it in enumerate(items)]
        try:
            res = _ask_json(client, model, ENRICH_SYSTEM.replace("{keys}", ", ".join(keys)),
                            json.dumps(payload, ensure_ascii=False))
            by_id = {r["id"]: r for r in res if isinstance(r, dict) and "id" in r}
            for i, it in enumerate(items):
                r = by_id.get(i, {})
                it["summary"] = r.get("summary", "")
                it["tags"] = [t for t in r.get("tags", []) if t in keys]
                it["direction"] = r.get("direction", "none")
                it["importance"] = int(r.get("importance", 1) or 1)
            items.sort(key=lambda x: -x.get("importance", 1))  # 안정 정렬: 같은 중요도는 최신순 유지
        except Exception as e:  # noqa: BLE001
            print(f"[news] 요약 실패({group}): {e}")
    return news
