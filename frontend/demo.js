// config.js에서 demo: true일 때만 쓰이는 샘플 데이터 (API 호출 없이 화면 확인용)
(function () {
  if (!(window.APP_CONFIG || {}).demo) return;
  const rows = [
    { id: "s1", category: "stock", market: "KR", code: "000660", name: "SK하이닉스", qty: 30, avg: 172000, valueKRW: 0, costKRW: 0 },
    { id: "s2", category: "stock", market: "KR", code: "005930", name: "삼성전자", qty: 120, avg: 68400, valueKRW: 0, costKRW: 0 },
    { id: "s3", category: "stock", market: "US", excd: "NAS", code: "NVDA", name: "NVIDIA", qty: 25, avg: 118.4, valueKRW: 0, costKRW: 0 },
    { id: "b1", category: "bond", isin: "KR103502GXXX", name: "국고채 (샘플)", type: "국채", currency: "KRW", coupon: 3.25, months: 6, issueDate: "2024-06-10", maturity: "2034-06-10", nextPay: "2026-12-10", face: 10000000, cost: 10000000, value: 10180000, valueDate: "2026-11-01", valueKRW: 10180000, costKRW: 10000000 },
    { id: "i1", category: "irp", kind: "etf", code: "360750", name: "TIGER 미국S&P500", risk: "risk", qty: 520, avg: 18077, valueKRW: 0, costKRW: 0 },
    { id: "i2", category: "irp", kind: "deposit", name: "정기예금 1년 (샘플)", risk: "safe", principal: 8000000, rate: 3.1, startDate: "2026-03-01", maturity: "2027-03-01", valueKRW: 8150000, costKRW: 8000000 },
  ];
  const quotes = { "KR:000660": { price: 270000, change: 7350, rate: 2.8 }, "KR:005930": { price: 79100, change: 940, rate: 1.2 }, "US:NAS:NVDA": { price: 167.2, change: 1.0, rate: 0.6 }, "KR:360750": { price: 21615, change: 108, rate: 0.5 } };
  const strategy = {
    date: "2026-11-06", generatedAt: "2026-11-06T07:30",
    portfolio: {
      direction: "위험자산 비중 유지,\n반도체 쏠림은 점진적으로 완화", summary: "(샘플) 오늘 밤 고용지표 전까지 신규 위험 노출을 줄이고, 이후 금리 방향에 따라 채권 비중을 검토합니다.",
      stances: [{ name: "주식", stance: "유지", level: 0, note: "업종 쏠림 완화" }, { name: "채권", stance: "유지 → 확대 검토", level: 0, note: "지표 후 금리 확인" }, { name: "IRP", stance: "유지", level: 0, note: "추가 납입은 안전자산" }],
      todos: [{ priority: "오늘", title: "고용지표 발표 전 신규 매수 보류", why: "이벤트 직후 변동성 확대 가능", cat: "전체" }, { priority: "이번 주", title: "IRP 납입분 안전자산 배정", why: "위험자산 한도 근접", cat: "IRP" }],
      cautions: [{ title: "반도체 업종 쏠림", body: "주식 대부분이 반도체 관련입니다" }], diagnostics: [{ label: "위험자산 비중", value: "71%", pct: 71 }, { label: "반도체 쏠림", value: "62% / 상한 40%", pct: 100, warn: true }],
    },
    stocks: {
      tone: { label: "중립 · 선별 대응", level: 56 }, brief: [{ k: "간밤 미국 증시", v: "(샘플) 반도체 강세" }, { k: "오늘 국내 개장 전망", v: "(샘플) 강보합 출발" }, { k: "주목 섹터", v: "(샘플) 반도체" }],
      issues: [{ title: "(샘플) 메모리 업황 리포트", impact: "긍정", body: "샘플 이슈입니다.", stocks: ["SK하이닉스", "삼성전자"] }],
      scenarios: [{ name: "SK하이닉스", verdict: "매수", why: "(샘플) 수급·리포트 우호", entry: "262,000~266,000", stop: "248,000 이탈", state: "진입 구간 근접" }, { name: "삼성전자", verdict: "관망", why: "(샘플) 방향성 확인", entry: "—", stop: "74,000 이탈", state: "유지" }, { name: "NVIDIA", verdict: "관망", why: "(샘플) 실적 전", entry: "실적 후", stop: "$155 이탈", state: "미국장 대기" }],
      checkpoints: [{ when: "09:30", what: "개장 30분 수급", action: "외국인 순매도 전환 시 매수 보류", tag: "국내" }, { when: "22:30", what: "미국 고용지표", action: "시나리오별 대응", tag: "미국" }],
      events: [{ when: "11/20", what: "NVIDIA 실적" }],
      review: { date: "2026-11-05", hits: 2, total: 3, rate20: 62, items: [{ name: "SK하이닉스", was: "매수", ret: 2.8, hit: true }, { name: "삼성전자", was: "비중축소", ret: 1.2, hit: false }, { name: "NVIDIA", was: "관망", ret: 0.6, hit: true }], comment: "(샘플) 복기 코멘트" },
      sources: [{ title: "샘플 출처", url: "https://example.com" }],
    },
  };
  window.DEMO = {
    async api(path, opts) {
      await new Promise((r) => setTimeout(r, 120));
      if (path.startsWith("/portfolio")) return { rows, fx: 1400, settings: { irpAnnualTarget: 9000000 }, contributions: [{ amount: 6000000 }] };
      if (path.startsWith("/quotes")) return { quotes, fx: 1400, at: new Date().toISOString() };
      if (path.startsWith("/strategy/dates")) return { dates: ["2026-11-06", "2026-11-05"] };
      if (path.startsWith("/strategy")) return strategy;
      if (path.startsWith("/lookup/bond")) return { name: "국고채 (샘플)", type: "국채", coupon: 3.25, months: 6, issueDate: "2024-06-10", maturity: "2034-06-10", nextPay: "2026-12-10" };
      if (path.includes("code=000000")) throw new Error("국내에서 '000000' 종목을 찾지 못했습니다. 코드와 시장(거래소)을 확인해 주세요.");
      if (path.startsWith("/lookup/stock")) return { name: "샘플 종목", quote: { price: 12345 } };
      if (opts && opts.method) { const e = new Error("데모 모드에서는 저장되지 않습니다."); throw e; }
      return {};
    },
  };
})();
