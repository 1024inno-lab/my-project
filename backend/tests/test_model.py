import math

from common import market, model
from api import apply_trade


def rows_from(closes, vol=1000):
    return [{"date": f"2026{i:04d}", "close": c, "volume": vol} for i, c in enumerate(closes)]


def test_total_and_verdict():
    w = model.DEFAULT_WEIGHTS
    strong = {k: 2 for k in model.FACTOR_KEYS}
    assert model.total_score(strong, w) == 100
    assert model.verdict(100) == "매수"
    assert model.verdict(-30) == "비중축소"
    assert model.verdict(10) == "관망"
    assert sum(w.values()) == 100


def test_chart_score_uptrend():
    s, why = model.chart_score(rows_from([100 + i for i in range(40)]))
    assert s >= 2 and "20일선 위" in why


def test_chart_score_downtrend():
    s, _ = model.chart_score(rows_from([200 - i for i in range(40)]))
    assert s <= -2


def test_history_needs_data():
    s, why = model.history_score(rows_from([100] * 10))
    assert s == 0 and "부족" in why


def test_supply_score():
    rows = rows_from([100] * 30, vol=10000)
    flow = [{"date": "d", "foreign": 3000, "institution": 1000}] * 3
    s, _ = model.supply_score(flow, rows)
    assert s == 2


def test_update_weights_rules():
    w = dict(model.DEFAULT_WEIGHTS)
    stats = {k: (5, 10) for k in model.FACTOR_KEYS}
    stats["us_market"] = (9, 10)
    stats["news"] = (3, 10)
    stats["event"] = (2, 4)  # 표본 부족 → 보류
    new, reasons = model.update_weights(w, stats, locked={"macro"})
    assert math.isclose(sum(new.values()), 100, abs_tol=0.5)
    assert new["macro"] == w["macro"]            # 고정
    assert new["event"] == w["event"]            # 표본 부족
    assert new["us_market"] > w["us_market"]
    assert new["news"] < w["news"]
    for k in model.FACTOR_KEYS:
        assert abs(new[k] - w[k]) <= model.MAX_STEP + 0.5
        assert model.MIN_W <= new[k] <= model.MAX_W
    assert "us_market" in reasons


def test_factor_stats():
    js = [{"scores": {"supply": 1, "news": -1}, "ret": 1.2}, {"scores": {"supply": 2}, "ret": -0.5}]
    st = model.factor_stats(js)
    assert st["supply"] == (1, 2)
    assert st["news"] == (0, 1)


def test_trade_average_price():
    cur = {"code": "000660", "qty": 30, "avg": 172000}
    after, trade = apply_trade(cur, "buy", 10, 185000)
    assert after["qty"] == 40 and round(after["avg"]) == 175250
    after, trade = apply_trade(cur, "sell", 10, 185000)
    assert after["qty"] == 20 and trade["realized"] == 130000


def test_bond_next_payment():
    assert market.next_payment("2024-06-10", "2034-06-10", 6, "2026-11-06") == "2026-12-10"
    assert market.next_payment("2025-02-01", "2027-02-01", 0, "2026-11-06") == "2027-02-01"
    assert market.pay_cycle_months("6개월") == 6
    assert market.pay_cycle_months("만기일시") == 0
