"""평일 07:30(KST) 실행: 요인별 가중 채점 → 데일리 전략 생성 → 저장·메일 발송.

화면에는 STRATEGY 결과만 노출되고, 요인 점수·가중치는 JUDGMENT/MODEL에만 저장된다.
"""
import json
import traceback
from datetime import datetime, timedelta, timezone

from common import config, db, kis, llm, model, portfolio

KST = timezone(timedelta(hours=9))

SYSTEM_ANALYST = (
    "당신은 한국 개인투자자의 보유 주식을 매일 아침 점검하는 애널리스트입니다. "
    "반드시 웹 검색으로 최신 정보를 확인하고, 확인하지 못한 내용은 추측하지 말고 0점과 '확인된 이슈 없음'으로 둡니다. "
    "투자 권유가 아닌 참고용 분석이며, 모든 문장은 한국어로 간결하게 씁니다. 출력은 JSON 하나만."
)
SYSTEM_WRITER = (
    "당신은 개인투자자의 데일리 대응 전략을 정리하는 작성자입니다. 주어진 판단(매수/관망/비중축소)은 바꾸지 말고 "
    "근거와 대응 방법을 구체적인 가격·시간 기준으로 씁니다. 과장·확정적 표현을 피하고 한국어로 간결하게. 출력은 JSON 하나만."
)


def now_kst() -> datetime:
    return datetime.now(KST)


def stock_inputs(stocks: list[dict]) -> list[dict]:
    """정량 요인(수급·차트·과거 사례)과 가격 레벨 계산."""
    out = []
    for h in stocks:
        info = {"id": h["id"], "name": h.get("name") or h["code"], "code": h["code"], "market": h.get("market", "KR"),
                "excd": h.get("excd", "NAS"), "qty": h.get("qty"), "avg": h.get("avg"), "scores": {}, "evidence": {}}
        try:
            rows = kis.kr_daily(h["code"]) if info["market"] == "KR" else kis.us_daily(info["excd"], h["code"])
            closes = [r["close"] for r in rows if r["close"]]
            info.update(lastClose=closes[-1] if closes else None,
                        lastDate=rows[-1]["date"] if rows else None,
                        ma20=round(model.moving_avg(closes, 20), 2) if closes else None,
                        low20=min(closes[-20:]) if closes else None,
                        high20=max(closes[-20:]) if closes else None)
            s, why = model.chart_score(rows)
            info["scores"]["chart"], info["evidence"]["chart"] = s, why
            s, why = model.history_score(rows)
            info["scores"]["history"], info["evidence"]["history"] = s, why
            if info["market"] == "KR":
                s, why = model.supply_score(kis.kr_investor_flow(h["code"]), rows)
            else:
                s, why = 0, "해외 종목은 투자자별 수급 미제공"
            info["scores"]["supply"], info["evidence"]["supply"] = s, why
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            info["error"] = str(e)[:200]
        out.append(info)
    return out


def qualitative_scores(today: str, items: list[dict]) -> dict:
    listing = "\n".join(f"- {i['name']} ({i['code']}, {'국내' if i['market'] == 'KR' else '미국'})" for i in items)
    prompt = f"""오늘은 {today}(KST) 아침입니다. 아래 보유 주식에 대해 웹 검색으로 확인한 뒤 JSON으로 답하세요.

보유 주식:
{listing}

각 종목마다 아래 5개 요인을 -2(매우 부정)~+2(매우 긍정) 정수로 채점하고 근거를 한 문장으로:
- us_market: 간밤 미국 증시(지수·같은 업종 미국 기업·해당 종목 자체) 결과가 오늘 이 종목에 주는 영향
- report: 최근 1주 증권사 리포트의 투자의견·목표주가 변화
- news: 최근 24~48시간 뉴스·공시의 방향
- macro: 환율·금리·경제지표가 이 종목에 주는 영향
- event: 가까운 실적 발표·지표 발표 등 일정의 위험/기회(일정이 임박해 변동성이 크면 음수)

JSON 형식:
{{
  "tone": {{"label": "예: 중립 · 선별 대응", "level": 0~100 (0=방어, 50=중립, 100=공격)}},
  "brief": [{{"k": "간밤 미국 증시", "v": "..."}}, {{"k": "오늘 국내 개장 전망", "v": "..."}}, {{"k": "주목 섹터", "v": "..."}}],
  "issues": [{{"title": "...", "impact": "긍정|부정|중립", "body": "2~3문장", "stocks": ["종목명"]}}],  // 보유 종목에 영향 있는 것만 최대 4개
  "factors": {{"<종목코드>": {{"us_market": {{"score": 0, "why": "..."}}, "report": {{...}}, "news": {{...}}, "macro": {{...}}, "event": {{...}}}}}},
  "events": [{{"when": "MM/DD HH:MM", "what": "..."}}],  // 오늘~1주 내 보유 종목 관련 일정
  "sources": [{{"title": "...", "url": "https://..."}}]
}}"""
    return llm.ask_json(SYSTEM_ANALYST, prompt, search=True, max_uses=15)


def write_strategy(today: str, items: list[dict], qual: dict, snap: dict, review: dict | None, settings: dict) -> dict:
    stock_lines = [{
        "name": i["name"], "code": i["code"], "market": i["market"], "verdict": i["verdict"],
        "lastClose": i.get("lastClose"), "ma20": i.get("ma20"), "low20": i.get("low20"), "high20": i.get("high20"),
        "avg": i.get("avg"), "qty": i.get("qty"),
        "evidence": {model.FACTOR_LABELS[k]: v for k, v in i.get("evidence", {}).items()},
    } for i in items]
    cats = snap["categories"]
    holdings_brief = [{"category": r["category"], "name": r.get("name"), "valueKRW": r["valueKRW"],
                       "plPct": r["plPct"], "risk": r.get("risk"), "kind": r.get("kind"),
                       "maturity": r.get("maturity"), "nextPay": r.get("nextPay")} for r in snap["rows"]]
    prompt = f"""오늘은 {today}(KST)입니다. 두 부분을 JSON으로 작성하세요.

[A] 보유 주식 대응 전략 — 판단은 아래 'verdict'를 그대로 사용(변경 금지)
종목 데이터: {json.dumps(stock_lines, ensure_ascii=False)}
오늘 시장 메모: {json.dumps({k: qual.get(k) for k in ('tone', 'brief', 'issues', 'events')}, ensure_ascii=False)}
- scenarios: 종목별 {{name, verdict, why(근거 1~2문장), entry(진입·추가 구간, 가격 범위 또는 '—'), stop(손절·축소 기준), state(현재 상태 한 단어구)}}
  가격은 lastClose·ma20·low20·high20을 기준으로 현실적인 값을 쓰세요(국내 원 단위 정수, 미국 달러 소수 2자리).
- checkpoints: 오늘 장중·미국장 시간대별 {{when "HH:MM", what, action, tag "국내|미국"}} 4~7개
- reviewComment: 전일 복기 결과 {json.dumps(review or {}, ensure_ascii=False)} 를 보고 빗나간 원인과 오늘 달라진 점 2문장(복기 없으면 빈 문자열)

[B] 종합 포트폴리오 전략 — 주식·채권·IRP 전체 관점(종목 매매 타이밍은 [A]에서 다루므로 반복 금지)
자산 구분 합계: {json.dumps(cats, ensure_ascii=False)}
전체 위험자산 비중 {snap['riskRatio']}%, 달러 자산 노출 {snap['usdExposure']}%, IRP 위험자산 비중 {snap['irpRiskRatio']}% (법정 한도 70%)
보유 항목: {json.dumps(holdings_brief, ensure_ascii=False)}
본인 운용 원칙(있으면 반드시 반영): {json.dumps(settings.get('rules', {}), ensure_ascii=False)}
- direction: 전략 방향 한 문장(줄바꿈 \\n 가능), summary: 2문장
- stances: 주식·채권·IRP 각각 {{name, stance("축소|유지|확대|유지 → 확대 검토" 등), level(-1 축소, 0 유지, 1 확대), note}}
- todos: {{priority "오늘|이번 주|이번 달", title, why, cat "주식|채권|IRP|전체"}} 3~6개
- cautions: {{title, body}} 2~4개 (업종 쏠림·환율·한도·만기·오래된 평가금액 등)
- diagnostics: {{label, value(표시 문자열), pct(0~100 막대 길이), warn(true/false)}} 3~5개. 업종 쏠림은 보유 종목 업종을 판단해 계산

JSON 형식: {{"stocks": {{"scenarios": [...], "checkpoints": [...], "reviewComment": "..."}}, "portfolio": {{"direction": "...", "summary": "...", "stances": [...], "todos": [...], "cautions": [...], "diagnostics": [...]}}}}"""
    return llm.ask_json(SYSTEM_WRITER, prompt, search=False, max_tokens=10000)


def send_mail(today: str, strategy: dict) -> None:
    if not config.OWNER_EMAIL:
        return
    import boto3

    p, s = strategy["portfolio"], strategy["stocks"]
    rows = "".join(f"<tr><td>{x['name']}</td><td><b>{x['verdict']}</b></td><td>{x.get('why', '')}</td></tr>" for x in s.get("scenarios", []))
    todos = "".join(f"<li>[{t.get('priority')}] {t.get('title')}</li>" for t in p.get("todos", []))
    html = f"""<div style="font-family:sans-serif;max-width:680px">
<h2>{today} Invest Desk 데일리 전략</h2>
<h3>종합 포트폴리오: {p.get('direction', '').replace(chr(10), ' ')}</h3><ul>{todos}</ul>
<h3>보유 주식 대응 ({s.get('tone', {}).get('label', '')})</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse">{rows}</table>
<p><a href="{config.SITE_URL}">전체 전략 보기</a></p>
<p style="color:#666;font-size:12px">자동 생성된 참고 자료이며 투자 판단과 책임은 본인에게 있습니다.</p></div>"""
    boto3.client("ses").send_email(
        Source=config.SENDER_EMAIL, Destination={"ToAddresses": [config.OWNER_EMAIL]},
        Message={"Subject": {"Data": f"[Invest Desk] {today} 데일리 전략", "Charset": "UTF-8"},
                 "Body": {"Html": {"Data": html, "Charset": "UTF-8"}}})


def run(today: str | None = None) -> dict:
    today = today or now_kst().date().isoformat()
    holdings = portfolio.holdings()
    stocks = [h for h in holdings if h.get("category") == "stock"]
    weights = db.get("MODEL", "weights", {}).get("weights") or dict(model.DEFAULT_WEIGHTS)
    settings = db.get("SETTINGS", "main", {})
    snap = portfolio.snapshot()

    items = stock_inputs(stocks)
    qual = qualitative_scores(today, items) if items else {}
    for i in items:
        f = (qual.get("factors") or {}).get(i["code"], {})
        for k in ("us_market", "report", "news", "macro", "event"):
            i["scores"][k] = model.to_score((f.get(k) or {}).get("score", 0))
            i["evidence"][k] = (f.get(k) or {}).get("why", "")
        i["total"] = model.total_score(i["scores"], weights)
        i["verdict"] = model.verdict(i["total"])

    reviews = db.query("REVIEW", newest_first=True, limit=1)
    review = reviews[0] if reviews else None
    written = write_strategy(today, items, qual, snap, review, settings)

    strategy = {
        "date": today,
        "generatedAt": now_kst().isoformat(timespec="minutes"),
        "portfolio": written.get("portfolio", {}),
        "stocks": {
            "tone": qual.get("tone", {}), "brief": qual.get("brief", []), "issues": qual.get("issues", []),
            "scenarios": written.get("stocks", {}).get("scenarios", []),
            "checkpoints": written.get("stocks", {}).get("checkpoints", []),
            "events": qual.get("events", []),
            "review": {**(review or {}), "comment": written.get("stocks", {}).get("reviewComment", "")} if review else None,
            "sources": qual.get("sources", []),
        },
    }
    db.put("STRATEGY", today, strategy)
    db.put("JUDGMENT", today, {
        "date": today, "weights": weights,
        "items": [{k: i.get(k) for k in ("id", "code", "name", "market", "excd", "scores", "total", "verdict", "lastClose", "lastDate")} for i in items],
    })
    try:
        send_mail(today, strategy)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return {"date": today, "stocks": len(items)}


def handler(event, _context):
    if now_kst().weekday() >= 5 and not (event or {}).get("force"):
        return {"skipped": "weekend"}
    return run((event or {}).get("date"))
