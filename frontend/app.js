/* 투자 데스크 — 단일 페이지 앱 (빌드 도구 없음) */
(function () {
  const C = window.APP_CONFIG || {};
  const $app = document.getElementById("app");
  const S = { portfolio: null, strategy: null, dates: [], quotes: {}, fx: 0, quoteAt: null, live: false, view: "dashboard", strategyDate: null, done: {} };
  let pollTimer = null;

  // ---------- 유틸 ----------
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v === null || v === undefined || v === "" || isNaN(+v) ? null : +v);
  const krw = (v) => (num(v) === null ? "—" : Math.round(v).toLocaleString("ko-KR"));
  const signed = (v, f = krw) => (num(v) === null ? "—" : (v > 0 ? "+" : "") + f(v));
  const pct = (v, d = 2) => (num(v) === null ? "—" : (v > 0 ? "+" : "") + (+v).toFixed(d) + "%");
  const cls = (v) => (num(v) === null || +v === 0 ? "flat" : +v > 0 ? "up" : "down");
  const price = (v, cur) => (num(v) === null ? "—" : cur === "USD" ? "$" + (+v).toFixed(2) : krw(v));
  const todayKST = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const icon = {
    edit: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"/></svg>',
    refresh: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 3 21 9 15 9"/></svg>',
    close: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>',
    warn: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#B45309" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex:none;margin-top:2px"><path d="M12 3 2 20h20L12 3z"/><line x1="12" y1="10" x2="12" y2="14"/><line x1="12" y1="17" x2="12" y2="17.01"/></svg>',
    check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#15803D" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="5 12 10 17 19 7"/></svg>',
    logo: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></svg>',
  };
  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
  }

  // ---------- API ----------
  async function api(path, opts = {}) {
    if (C.demo) return window.DEMO.api(path, opts);
    const token = await Auth.token();
    if (!token) { Auth.login(); throw new Error("로그인이 필요합니다"); }
    const res = await fetch(C.apiUrl + path, {
      method: opts.method || "GET",
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { Auth.login(); throw new Error("로그인이 만료되었습니다"); }
    if (!res.ok) { const e = new Error(data.error || "요청 실패 (" + res.status + ")"); e.status = res.status; throw e; }
    return data;
  }

  // ---------- 시세 반영 계산 ----------
  const quoteKey = (h) => h.category === "stock" ? (h.market === "KR" ? "KR:" + h.code : "US:" + (h.excd || "NAS") + ":" + h.code)
    : (h.category === "irp" && h.kind === "etf" ? "KR:" + h.code : null);
  const isUSD = (h) => h.market === "US" || h.currency === "USD";

  function computed() {
    const P = S.portfolio; if (!P) return null;
    const fx = S.fx || P.fx || 1400;
    const cats = { stock: { value: 0, cost: 0, count: 0 }, bond: { value: 0, cost: 0, count: 0 }, irp: { value: 0, cost: 0, count: 0 } };
    let today = 0, usd = 0, risk = 0, irpRisk = 0;
    const rows = P.rows.map((h) => {
      const r = { ...h };
      const key = quoteKey(h);
      const q = key ? S.quotes[key] : null;
      const mult = isUSD(h) ? fx : 1;
      if (key) {
        const p = q && num(q.price) ? +q.price : num(h.price) || num(h.avg) || 0;
        r.price = p; r.rate = q && num(q.rate) !== null ? +q.rate : h.rate; r.live = !!(q && num(q.price));
        r.valueKRW = p * (+h.qty || 0) * mult; r.costKRW = (+h.avg || 0) * (+h.qty || 0) * mult;
        if (q && num(q.change) !== null) today += +q.change * (+h.qty || 0) * mult;
      }
      r.plKRW = r.valueKRW - r.costKRW; r.plPct = r.costKRW ? (r.valueKRW / r.costKRW - 1) * 100 : 0;
      if (cats[h.category]) { cats[h.category].value += r.valueKRW; cats[h.category].cost += r.costKRW; cats[h.category].count++; }
      if (mult !== 1) usd += r.valueKRW;
      if (h.category === "stock" || (h.category === "irp" && h.risk === "risk")) risk += r.valueKRW;
      if (h.category === "irp" && h.risk === "risk") irpRisk += r.valueKRW;
      return r;
    });
    const total = cats.stock.value + cats.bond.value + cats.irp.value;
    const cost = cats.stock.cost + cats.bond.cost + cats.irp.cost;
    Object.values(cats).forEach((c) => { c.weight = total ? (c.value / total) * 100 : 0; c.pl = c.value - c.cost; c.plPct = c.cost ? (c.value / c.cost - 1) * 100 : 0; });
    return { rows, cats, total, cost, pl: total - cost, plPct: cost ? (total / cost - 1) * 100 : 0, today, fx,
      usd: total ? (usd / total) * 100 : 0, risk: total ? (risk / total) * 100 : 0, irpRisk: cats.irp.value ? (irpRisk / cats.irp.value) * 100 : 0 };
  }

  // ---------- 장 시간 / 폴링 ----------
  function marketOpen() {
    const k = new Date(Date.now() + 9 * 3600e3); const d = k.getUTCDay(); const m = k.getUTCHours() * 60 + k.getUTCMinutes();
    const kr = d >= 1 && d <= 5 && m >= 540 && m <= 930;
    const us = (d >= 1 && d <= 5 && m >= 1350) || (d >= 2 && d <= 6 && m <= 360);
    return kr || us;
  }
  async function pollQuotes() {
    const P = S.portfolio; if (!P) return;
    const keys = [...new Set(P.rows.map(quoteKey).filter(Boolean))];
    if (keys.length) {
      try {
        const r = await api("/quotes?keys=" + encodeURIComponent(keys.join(",")));
        S.quotes = r.quotes || {}; S.fx = r.fx || S.fx; S.quoteAt = r.at; S.live = Object.values(S.quotes).some((q) => num(q.price));
        if (!document.querySelector(".overlay")) render();
      } catch (e) { S.live = false; }
    }
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollQuotes, marketOpen() ? 10000 : 60000);
  }

  // ---------- 데이터 로드 ----------
  async function loadPortfolio() { S.portfolio = await api("/portfolio"); S.fx = S.portfolio.fx; }
  async function loadStrategy(date) {
    try { S.strategy = await api("/strategy" + (date ? "?date=" + date : "")); S.strategyDate = S.strategy.date; }
    catch (e) { if (e.status === 404) S.strategy = null; else throw e; }
    try { S.dates = (await api("/strategy/dates")).dates || []; } catch (e) { S.dates = []; }
    try { S.done = JSON.parse(localStorage.getItem("todo-" + (S.strategyDate || "")) || "{}"); } catch (e) { S.done = {}; }
  }

  // ---------- 레이아웃 ----------
  function shell(inner) {
    const time = S.quoteAt ? new Date(S.quoteAt).toLocaleTimeString("en-GB", { hour12: false, timeZone: "Asia/Seoul" }) : "—";
    return `<header class="topbar"><div class="inner">
      <div class="brand">${icon.logo}<span>투자 데스크</span></div>
      <nav class="nav" aria-label="주 메뉴">
        <a href="#/dashboard" class="${S.view === "dashboard" ? "active" : ""}">대시보드</a>
        <a href="#/strategy" class="${S.view === "strategy" ? "active" : ""}">주식 대응 전략</a>
      </nav>
      <div class="top-right">
        <span><span class="dot ${S.live ? "live" : ""}"></span> ${S.live ? "KIS 실시간 시세" : "시세 대기"} · <span class="mono">${esc(time)}</span></span>
        <button class="btn small light" data-act="refresh">${icon.refresh} 시세 새로고침</button>
        ${C.demo ? "" : '<button class="btn small light" data-act="logout">로그아웃</button>'}
      </div></div></header><main>${inner}</main>`;
  }

  // ---------- 대시보드 ----------
  function viewDashboard() {
    const V = computed();
    if (!V) return '<div class="empty">불러오는 중…</div>';
    const stocks = V.rows.filter((r) => r.category === "stock");
    const bonds = V.rows.filter((r) => r.category === "bond");
    const irp = V.rows.filter((r) => r.category === "irp");
    const set = S.portfolio.settings || {};
    const contrib = (S.portfolio.contributions || []).reduce((a, c) => a + (+c.amount || 0), 0);
    const target = +set.irpAnnualTarget || 0;
    return `
    <div class="page-head"><div><p>${esc(todayKST())} · ${marketOpen() ? "장중" : "장 마감"}</p><h1>내 투자 현황</h1></div>
      <button class="btn primary" data-act="add" data-cat="stock">+ 보유 종목 추가</button></div>

    <section class="grid-auto" aria-label="전체 자산 요약">
      ${kpi("총 평가금액 (주식+채권+IRP)", "₩ " + krw(V.total), `원화 환산 · 환율 ${krw(V.fx)}원`, "")}
      ${kpi("총 평가손익", signed(V.pl), "수익률 " + pct(V.plPct), cls(V.pl))}
      ${kpi("오늘 손익 (실시간 시세 반영분)", signed(V.today), S.live ? "주식·ETF 전일 대비" : "시세 수신 전", cls(V.today))}
    </section>

    ${portfolioStrategy()}

    <section class="card pad" aria-labelledby="h-split" style="display:flex;flex-direction:column;gap:18px">
      <h2 id="h-split" style="margin:0;font-size:17px">자산 구분별 현황</h2>
      <div class="alloc-bar" role="img" aria-label="자산 구분 비중: 주식 ${V.cats.stock.weight.toFixed(0)}%, 채권 ${V.cats.bond.weight.toFixed(0)}%, IRP ${V.cats.irp.weight.toFixed(0)}%">
        <span style="width:${V.cats.stock.weight}%;background:#1E2A4A"></span><span style="width:${V.cats.bond.weight}%;background:#5B7BC0"></span><span style="width:${V.cats.irp.weight}%;background:#A9B8D9"></span>
      </div>
      <div class="grid-auto">
        ${catCard("주식", "#stocks", "#1E2A4A", V.cats.stock, stocks.length + "종목 · 현재가 실시간")}
        ${catCard("채권", "#bonds", "#5B7BC0", V.cats.bond, bonds.length + "종목 · 발행정보 ISIN 자동")}
        ${catCard("IRP", "#irp", "#A9B8D9", V.cats.irp, irp.length + "개 상품 · 위험자산 " + V.irpRisk.toFixed(0) + "%")}
      </div>
    </section>

    <div id="stocks" class="row-wrap">
      <section class="card grow-3" aria-labelledby="h-stock">
        <div class="card-head"><div><h2 id="h-stock">주식</h2><div class="sub">수량·평균단가 입력 · 현재가 KIS 실시간</div></div>
          <button class="btn small" data-act="add" data-cat="stock">+ 종목 추가</button></div>
        ${stocks.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>종목</th><th class="r">수량</th><th class="r">평균단가</th><th class="r">현재가</th><th class="r">등락률</th><th class="r">평가손익</th><th>오늘 판단</th><th></th></tr></thead><tbody>
          ${stocks.map((r) => { const sc = scenarioFor(r); const cur = r.market === "US" ? "USD" : "KRW"; return `<tr>
            <td class="name"><b>${esc(r.name || r.code)}</b><span>${esc(r.code)} · ${r.market === "US" ? esc(r.excd || "NAS") : "국내"}</span></td>
            <td class="r mono">${krw(r.qty)}</td><td class="r mono">${price(r.avg, cur)}</td>
            <td class="r"><b class="mono">${price(r.price, cur)}</b><span class="src ${r.live ? "live" : ""}">${r.live ? "● 실시간" : "직전 값"}</span></td>
            <td class="r mono ${cls(r.rate)}">${pct(r.rate)}</td>
            <td class="r mono ${cls(r.plKRW)}">${signed(r.plKRW)}<br><small>${pct(r.plPct, 1)}</small></td>
            <td>${sc ? verdictBadge(sc.verdict) : '<span class="muted">—</span>'}</td>
            <td><button class="icon-btn" aria-label="${esc(r.name)} 수정" data-act="edit" data-id="${esc(r.id)}">${icon.edit}</button></td></tr>`; }).join("")}
          </tbody></table></div>` : emptyRow("주식", "stock")}
      </section>
      <aside class="grow-1" style="display:flex;flex-direction:column;gap:24px">${stockSide()}</aside>
    </div>

    <section id="bonds" class="card" aria-labelledby="h-bond">
      <div class="card-head"><div><h2 id="h-bond">채권</h2><div class="sub">ISIN 입력 → 금리·이자주기·만기 자동 · 평가금액은 직접 갱신</div></div>
        <button class="btn small" data-act="add" data-cat="bond">+ 채권 추가</button></div>
      ${bonds.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>채권명</th><th>유형</th><th class="r">액면금액</th><th class="r">표면금리</th><th class="r">만기일</th><th class="r">평가금액</th><th class="r">평가손익</th><th class="r">다음 이자일</th><th></th></tr></thead><tbody>
        ${bonds.map((r) => `<tr><td class="name"><b>${esc(r.name)}</b><span>${esc(r.isin || "직접 입력")} · ${esc(r.currency || "KRW")}</span></td>
          <td>${esc(r.type || "—")}</td><td class="r mono">${price(r.face, r.currency)}</td><td class="r mono">${num(r.coupon) !== null ? (+r.coupon).toFixed(2) + "%" : "—"}</td>
          <td class="r mono">${esc(r.maturity || "—")}</td><td class="r"><b class="mono">${krw(r.valueKRW)}</b><span class="src">${esc(r.valueDate ? "기준 " + r.valueDate : "")}</span></td>
          <td class="r mono ${cls(r.plKRW)}">${signed(r.plKRW)}</td><td class="r mono">${esc(r.nextPay || "—")}</td>
          <td><button class="icon-btn" aria-label="${esc(r.name)} 수정" data-act="edit" data-id="${esc(r.id)}">${icon.edit}</button></td></tr>`).join("")}
        </tbody></table></div>` : emptyRow("채권", "bond")}
    </section>

    <section id="irp" class="card" aria-labelledby="h-irp">
      <div class="card-head"><div><h2 id="h-irp">IRP <span class="muted" style="font-weight:500;font-size:14px">· ${esc(set.irpProvider || "신한은행")} 개인형퇴직연금</span></h2><div class="sub">종목코드·수량 입력 · 상장 ETF는 KIS 실시간</div></div>
        <button class="btn small" data-act="add" data-cat="irp">+ 상품 추가</button></div>
      <div class="grid-auto" style="gap:1px;background:var(--line-2);border-bottom:1px solid var(--line)">
        <div style="background:#fff;padding:16px 22px;display:flex;flex-direction:column;gap:6px"><span class="muted" style="font-size:12px">올해 납입액</span>
          <b class="mono" style="font-size:18px">₩ ${krw(contrib)} <span class="muted" style="font-size:13px;font-weight:400">/ ${target ? krw(target) : "목표 미설정"}</span></b>
          <div class="meter"><span style="width:${target ? Math.min(100, (contrib / target) * 100) : 0}%"></span></div></div>
        <div style="background:#fff;padding:16px 22px;display:flex;flex-direction:column;gap:6px"><span class="muted" style="font-size:12px">위험자산 비중</span>
          <b class="mono" style="font-size:18px">${V.irpRisk.toFixed(0)}% <span class="muted" style="font-size:13px;font-weight:400">/ 한도 70%</span></b>
          <div class="meter"><span style="width:${Math.min(100, (V.irpRisk / 70) * 100)}%;background:${V.irpRisk > 63 ? "var(--warn)" : "var(--accent)"}"></span></div></div>
        <div style="background:#fff;padding:16px 22px;display:flex;flex-direction:column;gap:6px"><span class="muted" style="font-size:12px">누적 수익률</span>
          <b class="mono ${cls(V.cats.irp.plPct)}" style="font-size:18px">${pct(V.cats.irp.plPct, 1)}</b><span class="muted" style="font-size:12px">원금 ₩ ${krw(V.cats.irp.cost)} 기준</span></div>
      </div>
      ${irp.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>상품명 · 코드</th><th>위험 구분</th><th class="r">수량</th><th class="r">평균단가</th><th class="r">현재가</th><th class="r">등락률</th><th class="r">평가금액</th><th class="r">평가손익</th><th></th></tr></thead><tbody>
        ${irp.map((r) => `<tr><td class="name"><b>${esc(r.name)}</b><span>${esc(r.code || ({ fund: "펀드·TDF", deposit: "예금" }[r.kind] || ""))}</span></td>
          <td><span class="badge ${r.risk === "risk" ? "warn" : "ok"}">${r.risk === "risk" ? "위험" : "안전"}</span></td>
          <td class="r mono">${r.kind === "etf" ? krw(r.qty) : r.kind === "fund" ? krw(r.units) + "좌" : "—"}</td>
          <td class="r mono">${r.kind === "etf" ? krw(r.avg) : "—"}</td>
          <td class="r">${r.kind === "etf" ? `<b class="mono">${krw(r.price)}</b><span class="src ${r.live ? "live" : ""}">${r.live ? "● 실시간" : "직전 값"}</span>` : r.kind === "fund" ? `<b class="mono">${krw(r.nav)}</b><span class="src">기준가 직접 갱신</span>` : '<span class="src">이자 자동 계산</span>'}</td>
          <td class="r mono ${cls(r.rate)}">${r.kind === "etf" ? pct(r.rate) : "—"}</td>
          <td class="r"><b class="mono">${krw(r.valueKRW)}</b></td>
          <td class="r mono ${cls(r.plKRW)}">${signed(r.plKRW)}<br><small>${pct(r.plPct, 1)}</small></td>
          <td><button class="icon-btn" aria-label="${esc(r.name)} 수정" data-act="edit" data-id="${esc(r.id)}">${icon.edit}</button></td></tr>`).join("")}
        </tbody></table></div>` : emptyRow("IRP 상품", "irp")}
    </section>`;
  }
  const kpi = (label, value, sub, c) => `<div class="card kpi"><span class="label">${esc(label)}</span><span class="value ${c}">${esc(value)}</span><span class="sub ${c || "muted"}">${esc(sub)}</span></div>`;
  const catCard = (name, href, color, c, meta) => `<a class="cat-card" href="${href}"><span style="display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px"><span class="swatch" style="background:${color}"></span>${name}<span class="mono muted" style="margin-left:auto;font-size:14px">${c.weight.toFixed(0)}%</span></span>
    <span class="mono" style="font-size:22px;font-weight:600">₩ ${krw(c.value)}</span><span class="mono ${cls(c.pl)}" style="font-size:13px">${signed(c.pl)} (${pct(c.plPct, 1)})</span><span class="muted" style="font-size:12px;border-top:1px solid var(--line-2);padding-top:8px">${esc(meta)}</span></a>`;
  const emptyRow = (what, cat) => `<div class="empty">아직 등록한 ${what}이 없습니다.<br><button class="btn small" style="margin-top:10px" data-act="add" data-cat="${cat}">+ 추가하기</button></div>`;
  const verdictBadge = (v) => `<span class="badge ${v === "매수" || v === "추가매수" ? "up" : v === "비중축소" ? "down" : ""}">${esc(v)}</span>`;
  const scenarioFor = (r) => ((S.strategy && S.strategy.stocks && S.strategy.stocks.scenarios) || []).find((s) => s.name === r.name || s.code === r.code);

  function portfolioStrategy() {
    const p = S.strategy && S.strategy.portfolio;
    if (!p || !p.direction) return `<section class="card"><div class="guide-head"><div><h2>오늘의 종합 포트폴리오 전략</h2><span>주식·채권·IRP 전체 자산 진단</span></div></div>
      <div class="empty">아직 생성된 전략이 없습니다. 평일 07:30에 AWS 에이전트가 자동으로 만들고 메일로도 보내 드립니다.</div></section>`;
    const seg = (lv) => [-1, 0, 1].map((x) => `<span class="${x === +lv ? "on" : ""}"></span>`).join("");
    return `<section class="card" aria-labelledby="h-guide">
      <div class="guide-head"><div><h2 id="h-guide">오늘의 종합 포트폴리오 전략</h2><span>주식·채권·IRP 전체 자산 진단 · ${esc(S.strategy.generatedAt || "").replace("T", " ")} 생성</span></div>
        <a class="btn small light" href="#/strategy">보유 주식 대응 전략 보기</a></div>
      <div class="guide-body">
        <div class="row-wrap" style="gap:20px">
          <div style="flex:1 1 300px;display:flex;flex-direction:column;gap:8px"><span class="muted" style="font-size:13px;font-weight:600">전략 방향</span>
            <p class="direction">${esc(p.direction)}</p><p style="margin:0;color:var(--ink-2);line-height:1.65">${esc(p.summary)}</p></div>
          <div style="flex:1 1 420px;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px">
            ${(p.stances || []).map((s) => `<div class="stance"><span class="muted" style="font-size:13px">${esc(s.name)}</span><b style="font-size:17px">${esc(s.stance)}</b>
              <div class="seg" role="img" aria-label="${esc(s.name)}: ${esc(s.stance)}">${seg(s.level)}</div><div style="display:flex;justify-content:space-between;font-size:11px" class="muted"><span>축소</span><span>유지</span><span>확대</span></div>
              <span style="font-size:12px;color:var(--ink-2);line-height:1.5">${esc(s.note)}</span></div>`).join("")}
          </div>
        </div>
        <div class="row-wrap">
          <div style="flex:3 1 480px;min-width:0;display:flex;flex-direction:column;gap:10px"><h3 style="margin:0;font-size:16px">오늘의 행동 지침</h3>
            ${(p.todos || []).map((t, i) => `<label class="todo ${S.done[i] ? "done" : ""}"><input type="checkbox" data-todo="${i}" ${S.done[i] ? "checked" : ""}>
              <span class="badge ${t.priority === "오늘" ? "solid" : ""}">${esc(t.priority)}</span>
              <span style="flex:1;display:flex;flex-direction:column;gap:3px"><b class="t">${esc(t.title)}</b><span class="muted" style="font-size:13px;line-height:1.5">${esc(t.why)}</span></span>
              <span class="badge">${esc(t.cat)}</span></label>`).join("")}
          </div>
          <div style="flex:2 1 340px;min-width:0;display:flex;flex-direction:column;gap:16px">
            <div style="display:flex;flex-direction:column;gap:10px"><h3 style="margin:0;font-size:16px">유의사항</h3>
              ${(p.cautions || []).map((w) => `<div class="caution">${icon.warn}<span><b>${esc(w.title)}</b><br><span style="color:var(--ink-2);font-size:13px">${esc(w.body)}</span></span></div>`).join("")}</div>
            <div style="display:flex;flex-direction:column;gap:10px"><h3 style="margin:0;font-size:16px">포트폴리오 진단 지표</h3>
              ${(p.diagnostics || []).map((g) => `<div style="display:flex;flex-direction:column;gap:6px"><div style="display:flex;justify-content:space-between;font-size:13px"><span style="color:var(--ink-2)">${esc(g.label)}</span><b class="mono" style="color:${g.warn ? "var(--warn)" : "var(--ink)"}">${esc(g.value)}</b></div>
                <div class="meter"><span style="width:${Math.max(0, Math.min(100, +g.pct || 0))}%;background:${g.warn ? "var(--warn)" : "var(--accent)"}"></span></div></div>`).join("")}</div>
          </div>
        </div>
        <p class="disclaimer">자동 생성된 참고 자료이며 투자 판단과 책임은 본인에게 있습니다.</p>
      </div></section>`;
  }

  function stockSide() {
    const st = S.strategy && S.strategy.stocks;
    const sc = (st && st.scenarios) || [];
    const events = (st && st.events) || [];
    return `<section class="card pad" style="display:flex;flex-direction:column;gap:14px" aria-labelledby="h-today">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h2 id="h-today" style="margin:0;font-size:17px">주식 종목별 판단</h2><span class="muted" style="font-size:12px">${st ? "07:30 생성" : ""}</span></div>
      ${st && st.tone && st.tone.label ? `<div style="display:flex;gap:12px;align-items:center;background:var(--bg);border-radius:10px;padding:12px 14px"><span class="muted" style="font-size:13px">시장 톤</span><b>${esc(st.tone.label)}</b></div>` : ""}
      ${sc.length ? sc.slice(0, 6).map((s) => `<div style="display:flex;gap:12px;align-items:flex-start">${verdictBadge(s.verdict)}<span style="display:flex;flex-direction:column;gap:2px"><b>${esc(s.name)}</b><span class="muted" style="font-size:13px;line-height:1.5">${esc(s.why)}</span></span></div>`).join("") : '<p class="muted" style="margin:0">전략이 생성되면 여기에 표시됩니다.</p>'}
      <a class="btn primary" href="#/strategy" style="justify-content:center">종목별 대응 전략 보기</a></section>
      ${events.length ? `<section class="card pad" aria-labelledby="h-cal"><h2 id="h-cal" style="margin:0 0 6px;font-size:17px">체크 일정</h2>
        ${events.map((e) => `<div class="list-row"><span class="mono muted" style="width:80px;flex:none;font-size:12px">${esc(e.when)}</span><span>${esc(e.what)}</span></div>`).join("")}</section>` : ""}`;
  }

  // ---------- 주식 대응 전략 ----------
  function viewStrategy() {
    const s = S.strategy && S.strategy.stocks;
    const dateSel = S.dates.length ? `<label class="field" style="flex-direction:row;align-items:center;gap:8px"><span style="white-space:nowrap">날짜</span><select data-act="date" style="min-width:150px">${S.dates.map((d) => `<option ${d === S.strategyDate ? "selected" : ""}>${esc(d)}</option>`).join("")}</select></label>` : "";
    if (!s) return `<div class="page-head"><div><p>보유 주식 대상</p><h1>주식시장 대응 전략</h1></div>${dateSel}</div>
      <div class="card empty">아직 생성된 전략이 없습니다. 평일 07:30에 자동 생성됩니다.</div>`;
    const rv = s.review;
    return `<div class="page-head"><div><p>보유 주식 ${(s.scenarios || []).length}종목 대상 · ${esc((S.strategy.generatedAt || "").replace("T", " "))} 생성 · 자산 배분과 전체 전략은 <a href="#/dashboard">대시보드</a>에서</p>
      <h1>${esc(S.strategyDate)} 주식시장 대응 전략</h1></div>${dateSel}</div>

    <section class="card pad" style="display:flex;flex-wrap:wrap;gap:24px">
      <div style="flex:1 1 240px;display:flex;flex-direction:column;gap:12px"><span class="muted" style="font-size:13px;font-weight:600">오늘 주식시장 톤</span>
        <b style="font-size:24px">${esc((s.tone || {}).label || "—")}</b>
        <div role="img" aria-label="시장 톤 ${esc((s.tone || {}).level)} (0 방어, 100 공격)"><div class="meter" style="height:10px"><span style="height:10px;width:${Math.max(0, Math.min(100, +((s.tone || {}).level) || 50))}%"></span></div>
          <div class="muted" style="display:flex;justify-content:space-between;font-size:12px;margin-top:6px"><span>방어</span><span>중립</span><span>공격</span></div></div></div>
      <div style="flex:2 1 480px;display:flex;flex-direction:column;gap:10px"><span class="muted" style="font-size:13px;font-weight:600">개장 전 브리핑</span>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px">${(s.brief || []).map((b) => `<div><b style="font-size:12px;color:var(--ink-2)">${esc(b.k)}</b><p style="margin:4px 0 0;line-height:1.6">${esc(b.v)}</p></div>`).join("")}</div></div>
    </section>

    ${(s.issues || []).length ? `<section style="display:flex;flex-direction:column;gap:14px"><h2 class="big">보유 종목에 영향을 주는 오늘의 이슈</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">${s.issues.map((i, n) => `<article class="card issue">
        <div style="display:flex;justify-content:space-between"><span class="mono muted" style="font-size:13px">ISSUE ${String(n + 1).padStart(2, "0")}</span><span class="badge ${i.impact === "긍정" ? "up" : i.impact === "부정" ? "down" : ""}">${esc(i.impact)}</span></div>
        <h3>${esc(i.title)}</h3><p>${esc(i.body)}</p><div class="chips" style="border-top:1px solid var(--line-2);padding-top:10px"><span class="muted" style="font-size:12px">관련 보유:</span>${(i.stocks || []).map((x) => `<span class="badge">${esc(x)}</span>`).join("")}</div></article>`).join("")}</div></section>` : ""}

    <section class="card" aria-labelledby="h-scen"><div class="card-head"><h2 id="h-scen" class="big">보유 종목별 대응 시나리오</h2><span class="sub">판단은 매일 복기 결과로 보정됩니다</span></div>
      <div class="table-wrap"><table class="t" style="min-width:960px"><thead><tr><th>종목</th><th>판단</th><th>근거</th><th class="r">진입·추가 구간</th><th class="r">손절·축소 기준</th><th class="r">현재 상태</th></tr></thead><tbody>
      ${(s.scenarios || []).map((r) => `<tr><td><b>${esc(r.name)}</b></td><td>${verdictBadge(r.verdict)}</td><td style="color:var(--ink-2);line-height:1.55">${esc(r.why)}</td>
        <td class="r mono">${esc(r.entry)}</td><td class="r mono">${esc(r.stop)}</td><td class="r muted" style="font-size:13px">${esc(r.state)}</td></tr>`).join("")}
      </tbody></table></div></section>

    <div class="row-wrap">
      <section class="card pad grow-1" style="flex:1 1 420px" aria-labelledby="h-chk"><h2 id="h-chk" class="big" style="margin-bottom:6px">장중 체크포인트</h2>
        ${(s.checkpoints || []).map((e) => `<div class="list-row"><b class="mono" style="width:52px;flex:none">${esc(e.when)}</b><span style="flex:1;display:flex;flex-direction:column;gap:3px"><b>${esc(e.what)}</b><span class="muted" style="font-size:13px;line-height:1.5">${esc(e.action)}</span></span><span class="badge">${esc(e.tag)}</span></div>`).join("")}</section>
      <section class="card pad grow-1" style="flex:1 1 420px;display:flex;flex-direction:column;gap:8px" aria-labelledby="h-rev">
        <div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;align-items:baseline"><h2 id="h-rev" class="big">전일 전략 복기</h2>
          ${rv ? `<span class="muted" style="font-size:13px">${esc(rv.date)} 판단 ${rv.total}건 중 <b style="color:var(--ink)">${rv.hits}건 적중</b>${rv.rate20 !== null && rv.rate20 !== undefined ? " · 최근 20거래일 <b style='color:var(--ink)'>" + esc(rv.rate20) + "%</b>" : ""}</span>` : ""}</div>
        ${rv ? (rv.items || []).map((v) => `<div class="list-row" style="align-items:center;flex-wrap:wrap"><b style="flex:1 1 140px">${esc(v.name)}</b><span class="muted" style="font-size:13px">어제 판단 <b style="color:var(--ink)">${esc(v.was)}</b></span>
          <span class="mono ${cls(v.ret)}" style="width:64px;text-align:right">${pct(v.ret, 1)}</span><span class="badge ${v.hit ? "ok" : "warn"}">${v.hit ? "적중" : "빗나감"}</span></div>`).join("")
          + (rv.comment ? `<p style="margin:6px 0 0;font-size:13px;color:var(--ink-2);line-height:1.6;background:var(--bg);border-radius:8px;padding:10px 12px">${esc(rv.comment)}</p>` : "")
          : '<p class="muted" style="margin:0">첫 복기는 전략이 생성된 다음 거래일 아침에 표시됩니다.</p>'}
      </section>
    </div>

    ${(s.sources || []).length ? `<section class="card pad" style="display:flex;flex-direction:column;gap:10px"><h2 style="margin:0;font-size:15px">분석에 사용한 출처</h2>
      <div class="chips">${s.sources.filter((x) => /^https?:\/\//.test(x.url || "")).map((x) => `<a class="badge" style="font-weight:500;padding:8px 12px;text-decoration:none" href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || x.url)}</a>`).join("")}</div>
      <p class="disclaimer">이 전략은 자동 생성된 참고 자료이며 투자 판단과 책임은 본인에게 있습니다.</p></section>` : ""}`;
  }

  // ---------- 보유 종목 추가·수정 ----------
  const M = { open: false, tab: "stock", id: null, data: {}, action: "buy", found: null, busy: false };
  function openEditor(cat, id) {
    const cur = id ? (S.portfolio.rows.find((r) => r.id === id) || {}) : {};
    Object.assign(M, { open: true, tab: cur.category || cat || "stock", id: id || null, data: { ...cur }, action: id ? "buy" : "new", found: id ? { name: cur.name } : null, busy: false });
    if (!id) M.data = { category: M.tab, market: "KR", excd: "NAS", kind: "etf", risk: "risk", currency: "KRW" };
    drawModal();
  }
  function closeEditor() { M.open = false; const o = document.querySelector(".overlay"); if (o) o.remove(); render(); }
  const f = (name, label, value, attrs = "") => `<label class="field">${label}<input name="${name}" value="${esc(value ?? "")}" ${attrs}></label>`;
  const sel = (name, label, value, opts) => `<label class="field">${label}<select name="${name}">${opts.map(([v, t]) => `<option value="${v}" ${String(value) === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>`;

  function editorBody() {
    const d = M.data;
    if (M.tab === "stock") {
      const existing = !!M.id;
      const isTrade = existing && M.action !== "fix";
      return `${existing ? `<div class="pills" role="group" aria-label="변경 내용">${[["buy", "매수 추가"], ["sell", "일부 매도"], ["close", "전량 매도"], ["fix", "직접 수정"]].map(([k, t]) => `<button type="button" data-action="${k}" class="${M.action === k ? "on" : ""}" aria-pressed="${M.action === k}">${t}</button>`).join("")}</div>` : ""}
        <div class="fields">${sel("market", "시장", d.market, [["KR", "국내 (KOSPI·KOSDAQ)"], ["US", "미국"]])}
          ${d.market === "US" ? sel("excd", "거래소", d.excd, [["NAS", "NASDAQ"], ["NYS", "NYSE"], ["AMS", "AMEX"]]) : ""}</div>
        <label class="field">종목코드<span class="inline"><input name="code" value="${esc(d.code || "")}" placeholder="${d.market === "US" ? "예: NVDA" : "예: 005930"}" ${existing ? "readonly" : ""}><button type="button" class="btn" data-act="lookup">종목 검색</button></span></label>
        ${M.found ? `<div class="found good">${icon.check}<span><b>${esc(M.found.name || d.name || d.code)}</b>${M.found.price ? " · 현재가 " + price(M.found.price, d.market === "US" ? "USD" : "KRW") + ' <span style="color:var(--ok)">● 실시간</span>' : ""}</span></div>` : ""}
        ${f("name", "종목명 (검색 시 자동)", d.name)}
        ${isTrade ? `<div class="fields">${M.action !== "close" ? f("tqty", M.action === "buy" ? "추가 매수 수량" : "매도 수량", "", 'inputmode="decimal"') : ""}${f("tprice", M.action === "buy" ? "매수 단가" : "매도 단가", "", 'inputmode="decimal"')}${f("tdate", "거래일", todayKST())}</div>
          <div class="preview" id="trade-preview"></div>`
        : `<div class="fields">${f("qty", "보유 수량", d.qty, 'inputmode="decimal"')}${f("avg", "평균 단가", d.avg, 'inputmode="decimal"')}</div>`}
        ${f("memo", "메모 (선택)", d.memo, 'placeholder="예: 실적 발표 전 분할 매수 1차"')}`;
    }
    if (M.tab === "bond") {
      const manual = d.currency === "USD" || d.manual;
      return `${manual ? "" : `<label class="field">채권 표준코드 (ISIN · 12자리)<span class="inline"><input name="isin" value="${esc(d.isin || "")}" placeholder="KR로 시작하는 12자리" class="mono"><button type="button" class="btn" data-act="lookup">채권 조회</button></span></label>`}
        ${M.found && !manual ? `<div class="found good">${icon.check}<span><b>발행 정보 자동 입력됨</b> · 금융위원회 채권기본정보</span></div>` : ""}
        ${f("name", "채권명", d.name)}
        <div class="fields">${f("type", "유형", d.type, 'placeholder="국채·회사채 등"')}${sel("currency", "통화", d.currency || "KRW", [["KRW", "KRW"], ["USD", "USD"]])}${f("coupon", "표면금리 (%)", d.coupon, 'inputmode="decimal"')}</div>
        <div class="fields">${f("months", "이자 지급 간격(개월, 만기일시=0)", d.months, 'inputmode="numeric"')}${f("issueDate", "발행일", d.issueDate, 'placeholder="YYYY-MM-DD"')}${f("maturity", "만기일", d.maturity, 'placeholder="YYYY-MM-DD"')}</div>
        <div class="fields">${f("face", "보유 액면금액", d.face, 'inputmode="decimal"')}${f("cost", "매입금액", d.cost, 'inputmode="decimal"')}${f("buyDate", "매입일", d.buyDate, 'placeholder="YYYY-MM-DD"')}</div>
        <div class="fields">${f("value", "현재 평가금액", d.value, 'inputmode="decimal"')}${f("valueDate", "평가 기준일", d.valueDate || todayKST())}</div>
        <p class="help">${manual ? "해외채권은 ISIN 자동 조회 대상이 아니어서 발행 정보를 직접 입력합니다." : '해외채권(미국채 등)은 통화를 USD로 바꾸면 직접 입력으로 전환됩니다.'} 평가금액은 증권사 앱 기준으로 가끔 갱신해 주세요.</p>`;
    }
    // IRP
    const kind = d.kind || "etf";
    return `<div class="fields">${sel("kind", "상품 유형", kind, [["etf", "상장 ETF (실시간 시세)"], ["fund", "펀드·TDF"], ["deposit", "예금·원리금보장"]])}${sel("risk", "위험 구분", d.risk || "risk", [["risk", "위험자산"], ["safe", "안전자산"]])}</div>
      ${kind === "etf" ? `<label class="field">종목코드<span class="inline"><input name="code" value="${esc(d.code || "")}" placeholder="예: 360750" ${M.id ? "readonly" : ""}><button type="button" class="btn" data-act="lookup">상품 검색</button></span></label>
        ${M.found ? `<div class="found good">${icon.check}<span><b>${esc(M.found.name || d.name)}</b>${M.found.price ? " · 현재가 " + krw(M.found.price) + ' <span style="color:var(--ok)">● 실시간</span>' : ""}</span></div>` : ""}
        ${f("name", "상품명 (검색 시 자동)", d.name)}<div class="fields">${f("qty", "보유 수량", d.qty, 'inputmode="decimal"')}${f("avg", "평균 매입단가", d.avg, 'inputmode="decimal"')}</div>`
      : kind === "fund" ? `${f("name", "펀드명", d.name)}<div class="fields">${f("units", "보유 좌수", d.units, 'inputmode="decimal"')}${f("nav", "기준가 (1,000좌당)", d.nav, 'inputmode="decimal"')}${f("principal", "매입 원금", d.principal, 'inputmode="decimal"')}</div>
        <p class="help">펀드·TDF는 KIS 시세가 없어 기준가를 가끔 직접 갱신합니다.</p>`
      : `${f("name", "상품명", d.name)}<div class="fields">${f("principal", "원금", d.principal, 'inputmode="decimal"')}${f("rate", "연 금리 (%)", d.rate, 'inputmode="decimal"')}${f("startDate", "가입일", d.startDate, 'placeholder="YYYY-MM-DD"')}${f("maturity", "만기일", d.maturity, 'placeholder="YYYY-MM-DD"')}</div>`}
      <div class="preview" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))"><span><small>이번 납입액 (선택)</small><input name="camount" inputmode="decimal" placeholder="예: 500,000" style="min-height:40px;border:1px solid #C9CFD9;border-radius:8px;padding:0 10px"></span>
        <span><small>납입일</small><input name="cdate" value="${todayKST()}" style="min-height:40px;border:1px solid #C9CFD9;border-radius:8px;padding:0 10px"></span></div>`;
  }

  function drawModal() {
    let o = document.querySelector(".overlay");
    if (!o) { o = document.createElement("div"); o.className = "overlay"; document.body.appendChild(o); }
    o.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <div class="modal-head"><div><h2 id="dlg-title">${M.id ? "보유 종목 수정" : "보유 종목 추가"}</h2><span class="muted" style="font-size:13px">저장하면 대시보드와 내일 아침 전략 분석에 반영됩니다</span></div>
        <button class="icon-btn" aria-label="닫기" data-act="close">${icon.close}</button></div>
      ${M.id ? "" : `<div class="tabs" role="tablist">${[["stock", "주식"], ["bond", "채권"], ["irp", "IRP"]].map(([k, t]) => `<button role="tab" aria-selected="${M.tab === k}" class="${M.tab === k ? "on" : ""}" data-tab="${k}">${t}</button>`).join("")}</div>`}
      <form class="modal-body" id="editor" autocomplete="off">${editorBody()}</form>
      <div class="modal-foot">${M.id ? '<button class="btn danger" data-act="delete">이 항목 삭제</button>' : ""}<span style="flex:1"></span>
        <button class="btn" data-act="close">취소</button><button class="btn primary" data-act="save" ${M.busy ? "disabled" : ""}>${M.busy ? "저장 중…" : "저장"}</button></div></div>`;
    updatePreview();
  }
  function readForm() {
    const form = document.getElementById("editor"); if (!form) return;
    new FormData(form).forEach((v, k) => { M.data[k] = typeof v === "string" ? v.trim() : v; });
  }
  const n = (v) => (v === undefined || v === "" ? undefined : +String(v).replace(/,/g, ""));
  function updatePreview() {
    const box = document.getElementById("trade-preview"); if (!box) return;
    readForm();
    const cur = S.portfolio.rows.find((r) => r.id === M.id) || {};
    const q = +cur.qty || 0, a = +cur.avg || 0, tq = M.action === "close" ? q : n(M.data.tqty) || 0, tp = n(M.data.tprice) || 0;
    const ccy = cur.market === "US" ? "USD" : "KRW";
    if (M.action === "buy") {
      const nq = q + tq; box.innerHTML = `<span><small>보유 수량</small><b class="mono">${krw(q)} → ${krw(nq)}</b></span><span><small>평균 단가</small><b class="mono">${price(a, ccy)} → ${price(nq ? (q * a + tq * tp) / nq : 0, ccy)}</b></span><span><small>추가 매수 금액</small><b class="mono">${price(tq * tp, ccy)}</b></span>`;
    } else {
      const sq = Math.min(tq, q); box.innerHTML = `<span><small>보유 수량</small><b class="mono">${krw(q)} → ${krw(q - sq)}</b></span><span><small>평균 단가</small><b class="mono">${price(a, ccy)}</b></span><span><small>실현 손익</small><b class="mono ${cls((tp - a) * sq)}">${tp ? signed((tp - a) * sq, (v) => price(v, ccy)) : "—"}</b></span>`;
    }
  }

  async function lookup() {
    readForm();
    const d = M.data;
    try {
      if (M.tab === "bond") {
        const r = await api("/lookup/bond?isin=" + encodeURIComponent(d.isin || ""));
        Object.assign(M.data, { name: r.name, type: r.type, coupon: r.coupon, months: r.months, issueDate: r.issueDate, maturity: r.maturity, nextPay: r.nextPay, currency: "KRW" });
        M.found = r;
      } else {
        const market = M.tab === "irp" ? "KR" : d.market || "KR";
        const r = await api(`/lookup/stock?market=${market}&code=${encodeURIComponent(d.code || "")}&excd=${encodeURIComponent(d.excd || "NAS")}`);
        M.found = { name: r.name, price: r.quote && r.quote.price };
        if (r.name) M.data.name = r.name;
        if (M.tab === "irp" && r.name && /채|국채|단기|머니마켓|MMF|금리|TDF/i.test(r.name)) M.data.risk = "safe";
      }
      drawModal();
    } catch (e) { toast(e.message); }
  }

  async function save() {
    readForm();
    const d = M.data;
    let body;
    if (M.tab === "stock") {
      if (M.id && M.action !== "fix") body = { action: M.action, qty: n(d.tqty), price: n(d.tprice), date: d.tdate };
      else body = { category: "stock", market: d.market, excd: d.market === "US" ? d.excd : undefined, code: (d.code || "").toUpperCase(), name: d.name, qty: n(d.qty), avg: n(d.avg), memo: d.memo };
      if (!M.id && !body.code) return toast("종목코드를 입력해 주세요.");
    } else if (M.tab === "bond") {
      body = { category: "bond", isin: d.isin, name: d.name, type: d.type, currency: d.currency, coupon: n(d.coupon), months: n(d.months) || 0, issueDate: d.issueDate, maturity: d.maturity,
        face: n(d.face), cost: n(d.cost), buyDate: d.buyDate, value: n(d.value), valueDate: d.valueDate, manual: d.currency === "USD" };
      if (!body.name) return toast("채권명을 입력하거나 ISIN으로 조회해 주세요.");
    } else {
      body = { category: "irp", kind: d.kind, risk: d.risk, name: d.name, code: d.code, qty: n(d.qty), avg: n(d.avg), units: n(d.units), nav: n(d.nav), principal: n(d.principal),
        rate: n(d.rate), startDate: d.startDate, maturity: d.maturity, contribution: n(d.camount) ? { amount: n(d.camount), date: d.cdate } : undefined };
      if (body.kind === "etf" && body.qty && body.avg) body.principal = body.qty * body.avg;
      if (!body.name && !body.code) return toast("상품명이나 종목코드를 입력해 주세요.");
    }
    Object.keys(body).forEach((k) => body[k] === undefined && delete body[k]);
    M.busy = true; drawModal();
    try {
      await api(M.id ? "/holdings/" + M.id : "/holdings", { method: M.id ? "PUT" : "POST", body });
      await loadPortfolio(); closeEditor(); pollQuotes(); toast("저장했습니다.");
    } catch (e) { M.busy = false; drawModal(); toast(e.message); }
  }

  async function remove() {
    if (!confirm("이 항목을 삭제할까요?")) return;
    try { await api("/holdings/" + M.id, { method: "DELETE" }); await loadPortfolio(); closeEditor(); toast("삭제했습니다."); }
    catch (e) { toast(e.message); }
  }

  // ---------- 이벤트 ----------
  document.addEventListener("click", async (ev) => {
    const t = ev.target.closest("[data-act],[data-tab],[data-action]");
    if (!t) return;
    if (t.dataset.tab) { readForm(); M.tab = t.dataset.tab; M.found = null; M.data = { ...M.data, category: M.tab }; return drawModal(); }
    if (t.dataset.action) { readForm(); M.action = t.dataset.action; return drawModal(); }
    const a = t.dataset.act;
    if (a === "add") { ev.preventDefault(); openEditor(t.dataset.cat); }
    else if (a === "edit") openEditor(null, t.dataset.id);
    else if (a === "close") { ev.preventDefault(); closeEditor(); }
    else if (a === "save") { ev.preventDefault(); save(); }
    else if (a === "delete") { ev.preventDefault(); remove(); }
    else if (a === "lookup") { ev.preventDefault(); lookup(); }
    else if (a === "refresh") pollQuotes();
    else if (a === "logout") Auth.logout();
  });
  document.addEventListener("change", async (ev) => {
    const t = ev.target;
    if (t.dataset.todo !== undefined) {
      S.done[t.dataset.todo] = t.checked;
      try { localStorage.setItem("todo-" + S.strategyDate, JSON.stringify(S.done)); } catch (e) {}
      t.closest(".todo").classList.toggle("done", t.checked);
    } else if (t.dataset.act === "date") { await loadStrategy(t.value); render(); }
    else if (t.closest("#editor") && ["market", "kind", "currency"].includes(t.name)) { readForm(); M.found = null; drawModal(); }
  });
  document.addEventListener("input", (ev) => { if (ev.target.closest("#editor")) updatePreview(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && M.open) closeEditor(); });

  // ---------- 라우팅 ----------
  function render() {
    S.view = location.hash.startsWith("#/strategy") ? "strategy" : "dashboard";
    $app.innerHTML = shell(S.view === "strategy" ? viewStrategy() : viewDashboard());
  }
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });

  async function boot() {
    if (!C.demo && (!C.apiUrl || !C.clientId)) {
      $app.innerHTML = '<div class="login"><div class="card"><h1 style="margin:0;font-size:22px">설정이 필요합니다</h1><p class="muted">config.js에 API 주소와 로그인 정보가 없습니다. GitHub Actions 배포가 완료되면 자동으로 채워집니다.</p></div></div>';
      return;
    }
    try {
      if (!C.demo) {
        await Auth.handleCallback();
        if (!(await Auth.token())) {
          $app.innerHTML = '<div class="login"><div class="card"><div style="display:flex;justify-content:center"><span style="background:var(--accent);border-radius:12px;padding:10px;display:inline-flex">' + icon.logo + '</span></div><h1 style="margin:0;font-size:22px">투자 데스크</h1><p class="muted" style="margin:0">본인 계정으로 로그인해 주세요.</p><button class="btn primary" style="justify-content:center" id="login">로그인</button></div></div>';
          document.getElementById("login").onclick = () => Auth.login();
          return;
        }
      }
      $app.innerHTML = shell('<div class="empty">불러오는 중…</div>');
      await Promise.all([loadPortfolio(), loadStrategy()]);
      render(); pollQuotes();
    } catch (e) {
      $app.innerHTML = shell(`<div class="card empty">데이터를 불러오지 못했습니다.<br>${esc(e.message)}</div>`);
    }
  }
  boot();
})();
