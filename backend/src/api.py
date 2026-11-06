"""HTTP API (API Gateway HTTP API + Cognito JWT). 모든 경로는 로그인한 본인만 호출 가능."""
import json
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from common import db, kis, market, portfolio

KST = timezone(timedelta(hours=9))
CATEGORIES = {"stock", "bond", "irp"}


def _resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json; charset=utf-8"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def _num(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


# ---------- 보유 종목 ----------
def list_portfolio(_q, _b):
    snap = portfolio.snapshot()
    return {**snap, "settings": db.get("SETTINGS", "main", {}),
            "contributions": db.query("CONTRIB", prefix=_today()[:4])}


def create_holding(_q, body):
    cat = body.get("category")
    if cat not in CATEGORIES:
        return 400, {"error": "category는 stock / bond / irp 중 하나여야 합니다."}
    hid = uuid.uuid4().hex[:12]
    item = {**_clean(body), "id": hid, "updatedAt": _today()}
    if cat == "bond" and item.get("issueDate") and item.get("maturity"):
        item["nextPay"] = market.next_payment(item["issueDate"], item["maturity"], int(item.get("months") or 0), _today())
    db.put("HOLDING", hid, item)
    _record_contribution(body)
    return 201, item


def update_holding(_q, body, hid):
    cur = db.get("HOLDING", hid)
    if not cur:
        return 404, {"error": "보유 항목을 찾을 수 없습니다."}
    action = body.pop("action", "fix")
    if cur.get("category") == "stock" and action in ("buy", "sell", "close"):
        cur, trade = apply_trade(cur, action, _num(body.get("qty")), _num(body.get("price")))
        db.put("TRADE", f"{body.get('date') or _today()}#{hid}#{uuid.uuid4().hex[:4]}", {**trade, "code": cur["code"], "name": cur.get("name")})
        if cur["qty"] <= 0:
            db.delete("HOLDING", hid)
            return 200, {"deleted": True, "trade": trade}
    else:
        cur.update(_clean(body))
    cur["updatedAt"] = _today()
    if cur.get("category") == "bond" and cur.get("issueDate"):
        cur["nextPay"] = market.next_payment(cur["issueDate"], cur.get("maturity", ""), int(cur.get("months") or 0), _today())
    db.put("HOLDING", hid, cur)
    _record_contribution(body)
    return 200, cur


def apply_trade(cur: dict, action: str, qty: float, price: float) -> tuple[dict, dict]:
    """매수 추가 → 평균단가 재계산 / 매도 → 실현손익 계산."""
    cur = dict(cur)
    old_qty, old_avg = _num(cur.get("qty")), _num(cur.get("avg"))
    if action == "close":
        qty = old_qty
    if action == "buy":
        new_qty = old_qty + qty
        cur["avg"] = round((old_qty * old_avg + qty * price) / new_qty, 4) if new_qty else 0
        cur["qty"] = new_qty
        trade = {"side": "buy", "qty": qty, "price": price, "realized": 0}
    else:
        qty = min(qty, old_qty)
        cur["qty"] = old_qty - qty
        trade = {"side": "sell", "qty": qty, "price": price, "realized": round((price - old_avg) * qty, 2)}
    return cur, trade


def delete_holding(_q, _b, hid):
    db.delete("HOLDING", hid)
    return 200, {"deleted": True}


def _clean(body: dict) -> dict:
    blocked = {"id", "_sk", "contribution", "action"}
    return {k: v for k, v in body.items() if k not in blocked}


def _record_contribution(body: dict):
    c = body.get("contribution") or {}
    if _num(c.get("amount")) > 0:
        d = c.get("date") or _today()
        db.put("CONTRIB", f"{d}#{uuid.uuid4().hex[:6]}", {"date": d, "amount": _num(c["amount"])})


# ---------- 시세·조회 ----------
def quotes(q, _b):
    keys = [k for k in (q.get("keys") or "").split(",") if k][:40]
    return {"quotes": portfolio.fetch_quotes(keys), "fx": market.usd_krw(), "at": datetime.now(KST).isoformat()}


def lookup_stock(q, _b):
    mkt, code = (q.get("market") or "KR").upper(), (q.get("code") or "").strip().upper()
    if not code:
        return 400, {"error": "code가 필요합니다."}
    if mkt == "KR" and not re.fullmatch(r"[0-9A-Z]{6}", code):
        return 400, {"error": "국내 종목코드는 6자리입니다. 예) 005930"}
    try:
        if mkt == "KR":
            name, quote, excd = kis.kr_name(code), kis.kr_price(code), None
        else:
            excd = (q.get("excd") or "NAS").upper()
            name, quote = kis.us_name(excd, code), kis.us_price(excd, code)
    except kis.KISError as e:
        return 502, {"error": f"시세 조회 실패: {e}"}
    if not name and not quote.get("price"):
        where = "국내" if mkt == "KR" else f"미국 {excd}"
        return 404, {"error": f"{where}에서 '{code}' 종목을 찾지 못했습니다. 코드와 시장(거래소)을 확인해 주세요."}
    return {"market": mkt, "excd": excd, "code": code, "name": name, "quote": quote}


def lookup_bond(q, _b):
    isin = (q.get("isin") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", isin):
        return 400, {"error": "ISIN은 영문 2자리 + 10자리(총 12자리)입니다."}
    try:
        info = market.bond_info(isin)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        return 502, {"error": f"채권 발행정보 조회 실패(공공데이터포털): {e}"}
    if not info:
        return 404, {"error": "해당 ISIN의 발행 정보를 찾지 못했습니다. 해외채권이면 직접 입력해 주세요."}
    info["nextPay"] = market.next_payment(info.get("issueDate", ""), info.get("maturity", ""), info.get("months", 0), _today())
    info.pop("raw", None)
    return {"isin": isin, **info}


# ---------- 전략 (결과만) ----------
def get_strategy(q, _b):
    date = q.get("date")
    if date:
        s = db.get("STRATEGY", date)
    else:
        latest = db.query("STRATEGY", newest_first=True, limit=1)
        s = latest[0] if latest else None
    if not s:
        return 404, {"error": "아직 생성된 전략이 없습니다. 평일 07:30에 자동 생성됩니다."}
    s.pop("_sk", None)
    return s


def list_strategy_dates(_q, _b):
    return {"dates": [i["_sk"] for i in db.query("STRATEGY", newest_first=True, limit=60)]}


def settings(_q, body, method="GET"):
    if method == "PUT":
        cur = db.get("SETTINGS", "main", {})
        cur.update(body)
        db.put("SETTINGS", "main", cur)
        return cur
    return db.get("SETTINGS", "main", {})


ROUTES = [
    ("GET", r"/portfolio", list_portfolio),
    ("POST", r"/holdings", create_holding),
    ("PUT", r"/holdings/(?P<hid>[\w-]+)", update_holding),
    ("DELETE", r"/holdings/(?P<hid>[\w-]+)", delete_holding),
    ("GET", r"/quotes", quotes),
    ("GET", r"/lookup/stock", lookup_stock),
    ("GET", r"/lookup/bond", lookup_bond),
    ("GET", r"/strategy", get_strategy),
    ("GET", r"/strategy/dates", list_strategy_dates),
    ("GET", r"/settings", lambda q, b: settings(q, b, "GET")),
    ("PUT", r"/settings", lambda q, b: settings(q, b, "PUT")),
]


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "OPTIONS":  # CORS 사전 요청 — 헤더는 API Gateway가 붙인다
        return {"statusCode": 204, "headers": {}, "body": ""}
    path = event.get("rawPath", "/")
    stage = event.get("requestContext", {}).get("stage", "$default")
    if stage != "$default" and path.startswith(f"/{stage}"):
        path = path[len(stage) + 1:]
    q = event.get("queryStringParameters") or {}
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "JSON 형식이 아닙니다."})
    for m, pattern, fn in ROUTES:
        match = re.fullmatch(pattern, path)
        if m == method and match:
            try:
                result = fn(q, body, **match.groupdict())
            except kis.KISError as e:
                return _resp(502, {"error": str(e)})
            except RuntimeError as e:
                return _resp(503, {"error": str(e)})
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return _resp(500, {"error": "서버 오류가 발생했습니다. CloudWatch 로그를 확인해 주세요."})
            if isinstance(result, tuple):
                return _resp(*result)
            return _resp(200, result)
    return _resp(404, {"error": f"{method} {path} 경로가 없습니다."})
