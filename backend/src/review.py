"""평일 07:00(KST) 실행: 전 거래일 판단 vs 실제 결과 복기 → 요인 가중치 자동 조정.

국내 종목은 판단일 종가, 미국 종목은 판단일 밤 미국 정규장 종가로 평가한다.
결과는 REVIEW(전략 화면의 '전일 복기'에 쓰임)와 MODEL(화면 비노출)에 저장한다.
"""
import traceback
from datetime import datetime, timedelta, timezone

from common import db, kis, model

KST = timezone(timedelta(hours=9))
MARKET_PROXY = "069500"  # KODEX 200 — 시장 급락 감지용


def _next_close(rows: list[dict], after: str):
    for r in rows:
        if r["date"] > after and r["close"]:
            return r
    return None


def evaluate(judgment: dict) -> list[dict]:
    results = []
    for it in judgment.get("items", []):
        if not it.get("lastClose") or not it.get("lastDate"):
            continue
        try:
            rows = kis.kr_daily(it["code"], days=30) if it["market"] == "KR" else kis.us_daily(it.get("excd", "NAS"), it["code"])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        nxt = _next_close(rows, it["lastDate"])
        if not nxt:
            continue
        ret = (nxt["close"] / it["lastClose"] - 1) * 100
        results.append({**it, "ret": round(ret, 2), "hit": model.verdict_hit(it["verdict"], ret)})
    return results


def market_crashed(date_compact: str) -> bool:
    try:
        rows = kis.kr_daily(MARKET_PROXY, days=15)
        prev = [r for r in rows if r["date"] < date_compact]
        cur = [r for r in rows if r["date"] == date_compact]
        if prev and cur:
            return (cur[0]["close"] / prev[-1]["close"] - 1) * 100 <= model.CRASH_PAUSE
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return False


def run(today: str | None = None) -> dict:
    today = today or datetime.now(KST).date().isoformat()
    pending = [j for j in db.query("JUDGMENT", newest_first=True, limit=5)
               if j["_sk"] < today and not db.get("REVIEW", j["_sk"])]
    if not pending:
        return {"reviewed": None}
    judgment = pending[0]
    date = judgment["_sk"]
    results = evaluate(judgment)
    if not results:
        return {"reviewed": date, "note": "평가할 종가 없음(휴장일 등)"}

    # 판단 기록에 실제 결과를 붙여 둔다 (가중치 학습 표본)
    by_code = {r["code"]: r for r in results}
    judgment["items"] = [{**it, **({"ret": by_code[it["code"]]["ret"]} if it["code"] in by_code else {})} for it in judgment["items"]]
    judgment.pop("_sk", None)
    db.put("JUDGMENT", date, judgment)

    # 최근 20거래일 판단 적중률
    history = db.query("JUDGMENT", newest_first=True, limit=model.WINDOW_DAYS)
    samples = [it for j in history for it in j.get("items", []) if it.get("ret") is not None]
    rate20 = round(sum(model.verdict_hit(s["verdict"], s["ret"]) for s in samples) / len(samples) * 100) if samples else None

    hits = sum(1 for r in results if r["hit"])
    db.put("REVIEW", date, {
        "date": date, "hits": hits, "total": len(results), "rate20": rate20,
        "items": [{"name": r["name"], "was": r["verdict"], "ret": r["ret"], "hit": r["hit"]} for r in results],
    })

    # 가중치 조정 (화면 비노출)
    state = db.get("MODEL", "weights", {}) or {}
    weights = state.get("weights") or dict(model.DEFAULT_WEIGHTS)
    locked = set(state.get("locked", []))
    if market_crashed(date.replace("-", "")):
        db.put("MODEL", f"log#{today}", {"date": today, "paused": True, "why": "시장 급락으로 조정 정지"})
        return {"reviewed": date, "paused": True}
    stats = model.factor_stats(samples)
    new_weights, reasons = model.update_weights(weights, stats, locked)
    version = int(state.get("version", 0)) + (1 if reasons else 0)
    db.put("MODEL", "weights", {"weights": new_weights, "locked": sorted(locked), "version": version, "updated": today})
    db.put("MODEL", f"log#{today}", {"date": today, "version": version, "from": weights, "to": new_weights,
                                      "reasons": reasons, "stats": {k: list(v) for k, v in stats.items()}})
    return {"reviewed": date, "hits": f"{hits}/{len(results)}", "weightsChanged": list(reasons)}


def handler(event, _context):
    if datetime.now(KST).weekday() >= 5 and not (event or {}).get("force"):
        return {"skipped": "weekend"}
    return run((event or {}).get("date"))
