"""요인 가중 판단 모델 (백엔드 전용 — 화면에는 결과만 노출).

- 8개 요인을 종목마다 -2~+2로 채점한다.
- 종합점수 = Σ(점수 × 가중치%) / 2  → -100 ~ +100
- +25 이상 매수 / -25 이하 비중축소 / 그 사이 관망
- 장 마감 후 복기 결과로 가중치를 천천히 조정한다.
"""
from statistics import mean

FACTORS = [
    ("supply", "수급(외국인·기관)"),
    ("us_market", "미국장 결과"),
    ("chart", "차트·기술적"),
    ("report", "증권사 리포트"),
    ("news", "뉴스·공시"),
    ("history", "과거 유사 사례"),
    ("macro", "거시·환율·금리"),
    ("event", "이벤트 일정"),
]
FACTOR_KEYS = [k for k, _ in FACTORS]
FACTOR_LABELS = dict(FACTORS)
DEFAULT_WEIGHTS = {"supply": 18, "us_market": 14, "chart": 16, "report": 16,
                   "news": 16, "history": 8, "macro": 7, "event": 5}

BUY_THRESHOLD = 25
SELL_THRESHOLD = -25

# 가중치 학습 규칙
WINDOW_DAYS = 20
SMOOTHING = 0.2        # 새 가중치 = 기존 80% + 목표 20%
MAX_STEP = 2.0         # 하루 최대 변화폭(%p)
MIN_W, MAX_W = 3.0, 30.0
MIN_SAMPLES = 10
CRASH_PAUSE = -3.0     # 시장 대용 지표가 -3% 이하면 조정 정지


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def to_score(v: float) -> int:
    return int(clamp(round(v), -2, 2))


# ---------- 정량 요인 ----------
def moving_avg(values: list[float], n: int) -> float:
    return mean(values[-n:]) if len(values) >= n else (mean(values) if values else 0.0)


def chart_score(rows: list[dict]) -> tuple[int, str]:
    closes = [r["close"] for r in rows if r["close"]]
    vols = [r["volume"] for r in rows]
    if len(closes) < 21:
        return 0, "일봉 데이터 부족"
    last, ma5, ma20 = closes[-1], moving_avg(closes, 5), moving_avg(closes, 20)
    s = (1 if last > ma20 else -1) + (1 if ma5 > ma20 else -1)
    vol_ratio = vols[-1] / (moving_avg(vols[:-1], 20) or 1)
    if vol_ratio > 1.5 and s != 0:
        s += 1 if s > 0 else -1
    s = to_score(s)
    side = "위" if last > ma20 else "아래"
    return s, f"종가 20일선 {side}, 5일선 {'상향' if ma5 > ma20 else '하향'}, 거래량 20일 평균 대비 {vol_ratio:.1f}배"


def supply_score(flow: list[dict], rows: list[dict]) -> tuple[int, str]:
    if not flow or not rows:
        return 0, "수급 데이터 없음"
    recent = flow[-3:]
    net = sum(r["foreign"] + r["institution"] for r in recent)
    avg_vol = moving_avg([r["volume"] for r in rows], 20) or 1
    ratio = net / avg_vol * 100
    s = 2 if ratio > 5 else 1 if ratio > 1 else -2 if ratio < -5 else -1 if ratio < -1 else 0
    fdays = sum(1 for r in recent if r["foreign"] > 0)
    return s, f"최근 3일 외국인+기관 순매수 {net:,.0f}주(20일 평균 거래량의 {ratio:+.1f}%), 외국인 순매수 {fdays}/3일"


def history_score(rows: list[dict], horizon: int = 5) -> tuple[int, str]:
    """현재와 비슷한 상황(5일 수익률 ±2%p, 20일선 위/아래 동일)의 과거 이후 5일 수익률 평균."""
    closes = [r["close"] for r in rows if r["close"]]
    if len(closes) < 40:
        return 0, "과거 데이터 부족"

    def feat(t):
        r5 = closes[t] / closes[t - 5] - 1
        above = closes[t] > mean(closes[t - 19:t + 1])
        return r5, above

    cur_r5, cur_above = feat(len(closes) - 1)
    outcomes = []
    for t in range(20, len(closes) - horizon - 1):
        r5, above = feat(t)
        if above == cur_above and abs(r5 - cur_r5) < 0.02:
            outcomes.append(closes[t + horizon] / closes[t] - 1)
    if len(outcomes) < 5:
        return 0, f"유사 사례 {len(outcomes)}건 — 판단 보류"
    avg = mean(outcomes) * 100
    ups = sum(1 for o in outcomes if o > 0)
    return to_score(avg / 1.0), f"유사 사례 {len(outcomes)}건 중 {ups}건 5거래일 후 상승, 평균 {avg:+.1f}%"


# ---------- 종합 ----------
def total_score(scores: dict, weights: dict) -> int:
    return round(sum(scores.get(k, 0) * weights.get(k, 0) for k in FACTOR_KEYS) / 2)


def verdict(total: int) -> str:
    if total >= BUY_THRESHOLD:
        return "매수"
    if total <= SELL_THRESHOLD:
        return "비중축소"
    return "관망"


def verdict_hit(v: str, ret_pct: float) -> bool:
    if v == "매수":
        return ret_pct > 0
    if v == "비중축소":
        return ret_pct < 0
    return abs(ret_pct) < 1.5


# ---------- 가중치 학습 ----------
def factor_stats(judgments: list[dict]) -> dict:
    """judgments: [{scores:{factor:int}, ret: float}] → {factor: (hits, n)}"""
    stats = {k: [0, 0] for k in FACTOR_KEYS}
    for j in judgments:
        ret = j.get("ret")
        if ret is None or ret == 0:
            continue
        for k in FACTOR_KEYS:
            s = j["scores"].get(k, 0)
            if s == 0:
                continue
            stats[k][1] += 1
            if (s > 0) == (ret > 0):
                stats[k][0] += 1
    return {k: tuple(v) for k, v in stats.items()}


def update_weights(weights: dict, stats: dict, locked: set | None = None) -> tuple[dict, dict]:
    """복기 통계로 새 가중치 계산. 반환: (new_weights, reasons)"""
    locked = locked or set()
    cur = {k: float(weights.get(k, DEFAULT_WEIGHTS[k])) for k in FACTOR_KEYS}
    adjustable = [k for k in FACTOR_KEYS if k not in locked and stats.get(k, (0, 0))[1] >= MIN_SAMPLES]
    if not adjustable:
        return {k: round(v, 1) for k, v in cur.items()}, {}

    pool = sum(cur[k] for k in adjustable)
    edge = {k: max(stats[k][0] / stats[k][1] - 0.45, 0.02) for k in adjustable}
    edge_sum = sum(edge.values())
    target = {k: pool * edge[k] / edge_sum for k in adjustable}

    new = dict(cur)
    for k in adjustable:
        proposed = cur[k] * (1 - SMOOTHING) + target[k] * SMOOTHING
        step = clamp(proposed - cur[k], -MAX_STEP, MAX_STEP)
        new[k] = clamp(cur[k] + step, MIN_W, MAX_W)

    # 조정 대상끼리 합계를 원래 pool로 맞춘다 (고정·보류 요인은 그대로).
    # 하루 변화폭·범위 제한 안에 남은 여유만큼 비례 배분한다.
    for _ in range(5):
        diff = pool - sum(new[k] for k in adjustable)
        if abs(diff) < 0.05:
            break
        if diff > 0:
            room = {k: min(MAX_W, cur[k] + MAX_STEP) - new[k] for k in adjustable}
        else:
            room = {k: new[k] - max(MIN_W, cur[k] - MAX_STEP) for k in adjustable}
        total_room = sum(max(r, 0) for r in room.values())
        if total_room <= 0:
            break
        for k in adjustable:
            share = max(room[k], 0) / total_room
            new[k] += diff * min(1.0, total_room / abs(diff)) * share

    new = {k: round(v, 1) for k, v in new.items()}
    reasons = {k: f"적중 {stats[k][0]}/{stats[k][1]} → {cur[k]:.1f}%→{new[k]:.1f}%"
               for k in adjustable if abs(new[k] - cur[k]) >= 0.1}
    return new, reasons
