import json

import api
from common import db, portfolio


class FakeDB:
    def __init__(self):
        self.items = {}

    def put(self, pk, sk, data, ttl=None):
        self.items[(pk, sk)] = json.loads(json.dumps(data))

    def get(self, pk, sk, default=None):
        return self.items.get((pk, sk), default)

    def delete(self, pk, sk):
        self.items.pop((pk, sk), None)

    def query(self, pk, prefix=None, newest_first=False, limit=None):
        rows = sorted(((k[1], v) for k, v in self.items.items() if k[0] == pk and (not prefix or k[1].startswith(prefix))),
                      reverse=newest_first)
        rows = rows[:limit] if limit else rows
        return [dict(v, _sk=sk) for sk, v in rows]


def call(method, path, body=None, query=None):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}, "stage": "$default"},
             "queryStringParameters": query, "body": json.dumps(body) if body else None}
    r = api.handler(event, None)
    return r["statusCode"], json.loads(r["body"])


def test_holdings_flow(monkeypatch):
    fake = FakeDB()
    for name in ("put", "get", "delete", "query"):
        monkeypatch.setattr(db, name, getattr(fake, name))
    monkeypatch.setattr(portfolio, "fetch_quotes", lambda keys: {k: {"price": 200000, "rate": 1.0} for k in keys})
    monkeypatch.setattr(portfolio.market, "usd_krw", lambda: 1400.0)

    code, h = call("POST", "/holdings", {"category": "stock", "market": "KR", "code": "000660", "name": "SK하이닉스", "qty": 30, "avg": 172000})
    assert code == 201
    code, upd = call("PUT", f"/holdings/{h['id']}", {"action": "buy", "qty": 10, "price": 185000})
    assert code == 200 and upd["qty"] == 40

    call("POST", "/holdings", {"category": "irp", "kind": "deposit", "name": "정기예금", "principal": 1000000, "rate": 3.0,
                               "startDate": "2026-01-01", "maturity": "2027-01-01", "risk": "safe",
                               "contribution": {"amount": 500000, "date": "2026-11-06"}})
    code, p = call("GET", "/portfolio")
    assert code == 200
    assert p["categories"]["stock"]["value"] == 40 * 200000
    assert p["categories"]["irp"]["value"] > 1000000
    assert len(p["contributions"]) == 1

    code, _ = call("GET", "/strategy")
    assert code == 404
    code, _ = call("GET", "/nope")
    assert code == 404


def test_lookup_stock_validation(monkeypatch):
    fake = FakeDB()
    for name in ("put", "get", "delete", "query"):
        monkeypatch.setattr(db, name, getattr(fake, name))
    code, body = call("GET", "/lookup/stock", query={"market": "KR", "code": "12"})
    assert code == 400 and "6자리" in body["error"]
    monkeypatch.setattr(api.kis, "kr_name", lambda c: "")
    monkeypatch.setattr(api.kis, "kr_price", lambda c: {"price": 0.0})
    code, body = call("GET", "/lookup/stock", query={"market": "KR", "code": "999999"})
    assert code == 404 and "찾지 못했습니다" in body["error"]
    monkeypatch.setattr(api.kis, "kr_name", lambda c: "삼성전자")
    monkeypatch.setattr(api.kis, "kr_price", lambda c: {"price": 79100.0, "rate": 1.2})
    code, body = call("GET", "/lookup/stock", query={"market": "KR", "code": "005930"})
    assert code == 200 and body["name"] == "삼성전자"


def test_lookup_missing_key_message(monkeypatch):
    from common import config
    config._cache.update(values={k: "" for k in config.SECRET_KEYS}, at=1e18)
    monkeypatch.setattr(config, "SECRET_ARN", "")
    code, body = call("GET", "/lookup/stock", query={"market": "KR", "code": "005930"})
    assert code == 503 and "KIS_APP_KEY" in body["error"]
    config._cache.update(values=None, at=0)
