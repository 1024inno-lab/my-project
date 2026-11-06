"""한국투자증권 Open API client (REST, 실전투자 도메인).

Endpoints/TR IDs follow the public KIS Developers docs. If KIS changes one,
only this module needs updating.
"""
import json
import time
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


def access_token() -> str:
    now = time.time()
    if _token_mem.get("exp", 0) - now > 600:
        return _token_mem["token"]
    cached = db.get("CACHE", "kis-token")
    if cached and cached.get("exp", 0) - now > 3600:
        _token_mem.update(cached)
        return cached["token"]
    resp = _http("POST", "/oauth2/tokenP", {}, body={
        "grant_type": "client_credentials",
        "appkey": config.secret("KIS_APP_KEY"),
        "appsecret": config.secret("KIS_APP_SECRET"),
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
