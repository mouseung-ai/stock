"""알림: 급변·디커플링 감지 → 텔레그램 전송(같은 알림은 하루 한 번)."""
from __future__ import annotations

import os

import requests


def detect(built: dict, rules: dict) -> list[dict]:
    ser, out = built["series"], []

    def chk(key, thr, unit):
        s = ser.get(key)
        if not s or thr is None or s["chg"]["d1"] is None:
            return
        v = s["chg"]["d1"]
        if abs(v) >= float(thr):
            u = "bp" if unit == "bp" else "%"
            out.append({"id": f"{key}:{s['last_date']}", "level": "move",
                        "text": f"{s['name']} 하루 {v:+.1f}{u} (기준 ±{thr}{u})"})

    chk("US10Y", rules.get("US10Y_bp"), "bp")
    chk("KR10Y", rules.get("KR10Y_bp"), "bp")
    chk("USDKRW", rules.get("USDKRW_pct"), "%")
    chk("JPYKRW", rules.get("JPYKRW_pct"), "%")
    if rules.get("decoupling"):
        for anchor, rows in built["coupling"].items():
            aname = ser.get(anchor, {}).get("name", anchor)
            for r in rows:
                if r["status"] in ("decoupled_flip", "decoupled_fade", "new_coupling"):
                    kind = {"decoupled_flip": "방향 역전", "decoupled_fade": "관계 약화",
                            "new_coupling": "새로 동조"}[r["status"]]
                    out.append({"id": f"dec:{anchor}:{r['key']}:{r['status']}", "level": "decouple",
                                "text": f"{aname} ↔ {r['name']} {kind} (이전 5개월 {r['rho_l']:+.2f} → 최근 1개월 {r['rho_s']:+.2f})"})
    return out


def send(alerts: list[dict], state: dict, today: str) -> dict:
    """새 알림만 텔레그램으로. 디커플링은 상태가 유지되는 동안 반복하지 않음."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    sent = state.get("sent", {})
    new = [a for a in alerts if a["id"] not in sent]
    if new and token and chat:
        text = "📈 금리·환율 알림\n" + "\n".join(f"• {a['text']}" for a in new)
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=20)
        except Exception as e:  # noqa: BLE001
            print(f"[alert] 전송 실패: {e}")
    for a in new:
        sent[a["id"]] = today
    # 디커플링이 풀린 항목은 상태에서 지워, 다시 발생하면 또 알림
    active = {a["id"] for a in alerts}
    sent = {k: v for k, v in sent.items() if not k.startswith("dec:") or k in active}
    # 오래된 급변 알림 기록 정리(14일)
    sent = {k: v for k, v in sent.items() if k.startswith("dec:") or v >= _days_ago(today, 14)}
    return {"sent": sent}


def _days_ago(today: str, n: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(today) - dt.timedelta(days=n)).isoformat()
