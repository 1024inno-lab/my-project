"""한국투자증권 Open API client (REST, 실전투자 도메인).

Endpoints/TR IDs follow the public KIS Developers docs. If KIS changes one,
only this module needs updating.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config, db

KST = timezone(timedelta(hours=9))
_token_mem: dict = {}
_last_call = [0.0]
MIN_INTERVAL = 0.06  # 실전 계좌 초당 호출 제한 대비

US_EXCHANGES = {"NAS": "512", "NYS": "513", "AMS": "529"}


class KISError(RuntimeError):
    pass


def _http(method: str, path: str, headers: dict, params: dict | None = None, body: dict | None = None) -> dict:
    url = config.KIS_BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json; charset=utf-8", **headers})
    wait = MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _last_call[0] = time.time()
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:  # noqa: PERF203
        raise KISError(f"KIS {path} HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KISError(f"KIS 서버에 연결하지 못했습니다({path}): {e}") from e


def access_token() -> str:
    app_key, app_secret = config.secret("KIS_APP_KEY"), config.secret("KIS_APP_SECRET")  # 키 없으면 즉시 안내
    now = time.time()
    if _token_mem.get("exp", 0) - now > 600:
        return _token_mem["token"]
    cached = db.get("CACHE", "kis-token")
    if cached and cached.get("exp", 0) - now > 3600:
        _token_mem.update(cached)
        return cached["token"]
    resp = _http("POST", "/oauth2/tokenP", {}, body={
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    })
    if "access_token" not in resp:
        raise KISError(f"토큰 발급 실패: {resp}")
    exp = now + int(resp.get("expires_in", 86400))
    record = {"token": resp["access_token"], "exp": exp}
    db.put("CACHE", "kis-token", record, ttl=int(exp))
    _token_mem.update(record)
    return record["token"]


def _get(path: str, tr_id: str, params: dict) -> dict:
    headers = {
        "authorization": f"Bearer {access_token()}",
        "appkey": config.secret("KIS_APP_KEY"),
        "appsecret": config.secret("KIS_APP_SECRET"),
        "tr_id": tr_id,
        "custtype": "P",
    }
    resp = _http("GET", path, headers, params=params)
    if resp.get("rt_cd") not in (None, "0"):
        raise KISError(f"{tr_id} 오류: {resp.get('msg1')}")
    return resp


def _f(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


# ---------- 현재가 ----------
def kr_price(code: str) -> dict:
    out = _get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
               {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})["output"]
    return {"price": _f(out.get("stck_prpr")), "change": _f(out.get("prdy_vrss")),
            "rate": _f(out.get("prdy_ctrt")), "currency": "KRW"}


def us_price(excd: str, symbol: str) -> dict:
    out = _get("/uapi/overseas-price/v1/quotations/price", "HHDFS00000300",
               {"AUTH": "", "EXCD": excd, "SYMB": symbol})["output"]
    return {"price": _f(out.get("last")), "change": _f(out.get("diff")),
            "rate": _f(out.get("rate")), "currency": "USD"}


# ---------- 종목 검색 (이름) ----------
def kr_name(code: str) -> str:
    try:
        out = _get("/uapi/domestic-stock/v1/quotations/search-stock-info", "CTPF1002R",
                   {"PRDT_TYPE_CD": "300", "PDNO": code})["output"]
        return out.get("prdt_abrv_name") or out.get("prdt_name") or ""
    except KISError:
        return ""


def us_name(excd: str, symbol: str) -> str:
    try:
        out = _get("/uapi/overseas-price/v1/quotations/search-info", "CTPF1702R",
                   {"PRDT_TYPE_CD": US_EXCHANGES.get(excd, "512"), "PDNO": symbol})["output"]
        return out.get("prdt_eng_name") or out.get("prdt_name") or ""
    except KISError:
        return ""


# ---------- 일봉 (차트·과거 사례·복기) ----------
def kr_daily(code: str, days: int = 140) -> list[dict]:
    end = datetime.now(KST)
    start = end - timedelta(days=days)
    out = _get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100", {
        "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"), "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0",
    }).get("output2", [])
    rows = [{"date": r["stck_bsop_date"], "close": _f(r.get("stck_clpr")), "volume": _f(r.get("acml_vol"))}
            for r in out if r.get("stck_bsop_date")]
    return sorted(rows, key=lambda r: r["date"])


def us_daily(excd: str, symbol: str) -> list[dict]:
    out = _get("/uapi/overseas-price/v1/quotations/dailyprice", "HHDFS76240000", {
        "AUTH": "", "EXCD": excd, "SYMB": symbol, "GUBN": "0", "BYMD": "", "MODP": "1",
    }).get("output2", [])
    rows = [{"date": r["xymd"], "close": _f(r.get("clos")), "volume": _f(r.get("tvol"))}
            for r in out if r.get("xymd")]
    return sorted(rows, key=lambda r: r["date"])


# ---------- 투자자별 수급 (국내) ----------
def kr_investor_flow(code: str) -> list[dict]:
    out = _get("/uapi/domestic-stock/v1/quotations/inquire-investor", "FHKST01010900",
               {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}).get("output", [])
    rows = [{"date": r.get("stck_bsop_date"), "foreign": _f(r.get("frgn_ntby_qty")),
             "institution": _f(r.get("orgn_ntby_qty"))} for r in out if r.get("stck_bsop_date")]
    return sorted(rows, key=lambda r: r["date"])


# ---------- 주요 지수 (대시보드 차트) ----------
# 국내: 국내주식업종기간별시세 FHKUP03500100 (업종코드 0001 코스피, 1001 코스닥)
# 해외: 해외주식 종목·지수·환율 기간별시세 FHKST03030100 (N 해외지수, X 환율)
INDICES = [
    {"key": "KOSPI", "name": "코스피", "kind": "kr", "code": "0001"},
    {"key": "KOSDAQ", "name": "코스닥", "kind": "kr", "code": "1001"},
    {"key": "NASDAQ", "name": "나스닥", "kind": "N", "code": "COMP"},
    {"key": "SPX", "name": "S&P 500", "kind": "N", "code": "SPX"},
    {"key": "USDKRW", "name": "원/달러", "kind": "X", "code": "FX@KRW", "alt": "FX@KRWKFTC"},
]
PERIODS = {"1M": (31, "D"), "3M": (95, "D"), "1Y": (370, "W")}


def _series(rows: list, value_key: str) -> list[dict]:
    pts = [{"d": r.get("stck_bsop_date"), "v": _f(r.get(value_key))} for r in rows or []]
    return sorted([p for p in pts if p["d"] and p["v"]], key=lambda p: p["d"])


def index_chart(spec: dict, period: str = "3M") -> dict:
    days, unit = PERIODS.get(period, PERIODS["3M"])
    end = datetime.now(KST)
    d1, d2 = (end - timedelta(days=days)).strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if spec["kind"] == "kr":
        body = _get("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100", {
            "FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": spec["code"],
            "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": unit})
        o1 = body.get("output1") or {}
        cur = {"value": _f(o1.get("bstp_nmix_prpr")), "change": _f(o1.get("bstp_nmix_prdy_vrss")),
               "rate": _f(o1.get("bstp_nmix_prdy_ctrt"))}
        pts = _series(body.get("output2"), "bstp_nmix_prpr")
    else:
        body = None
        for code in (spec["code"], spec.get("alt")):
            if not code:
                continue
            try:
                body = _get("/uapi/overseas-price/v1/quotations/inquire-daily-chartprice", "FHKST03030100", {
                    "FID_COND_MRKT_DIV_CODE": spec["kind"], "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": unit})
                if body.get("output2"):
                    break
            except KISError:
                body = None
        if not body:
            raise KISError(f"{spec['name']} 시세를 받지 못했습니다")
        o1 = body.get("output1") or {}
        cur = {"value": _f(o1.get("ovrs_nmix_prpr")), "change": _f(o1.get("ovrs_nmix_prdy_vrss")),
               "rate": _f(o1.get("prdy_ctrt"))}
        pts = _series(body.get("output2"), "ovrs_nmix_prpr")
    if not cur["value"] and pts:
        cur["value"] = pts[-1]["v"]
    return {"key": spec["key"], "name": spec["name"], **cur, "points": pts}
