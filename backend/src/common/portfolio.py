"""보유 현황 계산: 평가금액·손익·자산 구분별 합계 (주식·채권·IRP)."""
from datetime import date

from . import db, kis, market


def holdings() -> list[dict]:
    return [h for h in db.query("HOLDING")]


def quote_key(h: dict) -> str | None:
    if h.get("category") == "stock":
        return f"KR:{h['code']}" if h.get("market") == "KR" else f"US:{h.get('excd', 'NAS')}:{h['code']}"
    if h.get("category") == "irp" and h.get("kind") == "etf":
        return f"KR:{h['code']}"
    return None


def fetch_quotes(keys: list[str]) -> dict:
    out = {}
    for key in sorted(set(keys)):
        parts = key.split(":")
        try:
            out[key] = kis.kr_price(parts[1]) if parts[0] == "KR" else kis.us_price(parts[1], parts[2])
        except Exception as e:  # noqa: BLE001
            out[key] = {"error": str(e)[:200]}
    return out


def deposit_value(h: dict, today: date) -> float:
    principal = float(h.get("principal") or 0)
    rate = float(h.get("rate") or 0) / 100
    start = date.fromisoformat(h["startDate"]) if h.get("startDate") else today
    end = date.fromisoformat(h["maturity"]) if h.get("maturity") else today
    days = max(0, (min(today, end) - start).days)
    return principal * (1 + rate * days / 365)


def valuate(items: list[dict], quotes: dict, fx: float, today: date | None = None) -> dict:
    """각 보유 항목에 value/cost/pl(원화)을 붙이고 구분별 합계를 낸다."""
    today = today or date.today()
    rows, cats = [], {c: {"value": 0.0, "cost": 0.0, "count": 0} for c in ("stock", "bond", "irp")}
    usd_value = risk_value = 0.0
    for h in items:
        cat = h.get("category")
        r = dict(h)
        q = quotes.get(quote_key(h) or "", {})
        mult = fx if (h.get("market") == "US" or h.get("currency") == "USD") else 1.0
        if cat in ("stock",) or (cat == "irp" and h.get("kind") == "etf"):
            price = q.get("price") or float(h.get("lastPrice") or h.get("avg") or 0)
            r.update(price=price, rate=q.get("rate"), live="price" in q)
            value = price * float(h.get("qty") or 0) * mult
            cost = float(h.get("avg") or 0) * float(h.get("qty") or 0) * mult
        elif cat == "irp" and h.get("kind") == "deposit":
            value, cost = deposit_value(h, today), float(h.get("principal") or 0)
        elif cat == "irp":  # 펀드·TDF: 기준가 × 좌수 또는 평가금액 직접 입력
            nav, units = float(h.get("nav") or 0), float(h.get("units") or 0)
            value = nav * units / 1000 if nav and units else float(h.get("value") or 0)
            cost = float(h.get("principal") or 0)
        else:  # bond
            value = float(h.get("value") or h.get("cost") or 0) * mult
            cost = float(h.get("cost") or 0) * mult
        r.update(valueKRW=round(value), costKRW=round(cost), plKRW=round(value - cost),
                 plPct=round((value / cost - 1) * 100, 2) if cost else 0.0)
        rows.append(r)
        if cat in cats:
            cats[cat]["value"] += value
            cats[cat]["cost"] += cost
            cats[cat]["count"] += 1
        if mult != 1.0:
            usd_value += value
        if cat == "stock" or (cat == "irp" and h.get("risk") == "risk"):
            risk_value += value
    total = sum(c["value"] for c in cats.values())
    cost = sum(c["cost"] for c in cats.values())
    irp_total = cats["irp"]["value"]
    irp_risk = sum(r["valueKRW"] for r in rows if r.get("category") == "irp" and r.get("risk") == "risk")
    return {
        "rows": rows,
        "categories": {k: {**v, "value": round(v["value"]), "cost": round(v["cost"]),
                           "weight": round(v["value"] / total * 100, 1) if total else 0} for k, v in cats.items()},
        "total": round(total), "cost": round(cost), "pl": round(total - cost),
        "plPct": round((total / cost - 1) * 100, 2) if cost else 0,
        "usdExposure": round(usd_value / total * 100, 1) if total else 0,
        "riskRatio": round(risk_value / total * 100, 1) if total else 0,
        "irpRiskRatio": round(irp_risk / irp_total * 100, 1) if irp_total else 0,
        "fx": fx,
    }


def snapshot() -> dict:
    items = holdings()
    quotes = fetch_quotes([k for k in (quote_key(h) for h in items) if k])
    return valuate(items, quotes, market.usd_krw())
