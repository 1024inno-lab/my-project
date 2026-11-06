"""시세 이외의 시장 데이터: 채권 발행정보(공공데이터포털), 환율."""
import json
import time
import urllib.parse
import urllib.request

from . import config

BOND_URL = "https://apis.data.go.kr/1160100/service/GetBondIssuInfoService/getBondBasiInfo"
_fx_cache: dict = {}

# 응답 필드명은 공공데이터포털 명세 기준. 명세가 바뀌어도 동작하도록 후보를 여러 개 둔다.
BOND_FIELDS = {
    "name": ("isinCdNm", "bondIsurNm", "itmsNm"),
    "coupon": ("bondSrfcInrt", "srfcInrt"),
    "payCycle": ("intPayCyclCtt", "bondIntPayCyclCtt", "intPayCycl"),
    "issueDate": ("bondIssuDt", "issuDt"),
    "maturity": ("bondExprDt", "exprDt"),
    "type": ("scrsItmsKcdNm", "bondKndNm", "bondIssuKndNm"),
    "rateType": ("irtChngDcdNm", "intrRtChgDcdNm"),
    "currency": ("bondIssuCurCdNm", "curCd"),
}


def _pick(row: dict, keys: tuple):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return ""


def _fmt_date(v: str) -> str:
    v = str(v or "")
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else v


def bond_info(isin: str) -> dict:
    params = {"serviceKey": config.secret("DATA_GO_KR_KEY"), "resultType": "json",
              "numOfRows": "1", "pageNo": "1", "isinCd": isin.strip().upper()}
    url = BOND_URL + "?" + urllib.parse.urlencode(params, safe="%")
    with urllib.request.urlopen(url, timeout=10) as resp:
        payload = json.loads(resp.read().decode())
    items = payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]
    if not items:
        return {}
    row = items[0]
    info = {key: _pick(row, keys) for key, keys in BOND_FIELDS.items()}
    info["issueDate"] = _fmt_date(info["issueDate"])
    info["maturity"] = _fmt_date(info["maturity"])
    try:
        info["coupon"] = float(info["coupon"])
    except (TypeError, ValueError):
        pass
    info["months"] = pay_cycle_months(str(info.get("payCycle", "")))
    info["raw"] = row
    return info


def pay_cycle_months(text: str) -> int:
    """'6개월', '3', '이표채(6월)' 등에서 지급 간격(개월)을 뽑는다. 0 = 만기 일시."""
    import re

    if any(w in text for w in ("만기", "할인", "복리")):
        return 0
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def next_payment(issue_date: str, maturity: str, months: int, today: str) -> str:
    """발행일부터 months 간격으로 굴려 today 이후 첫 이자일."""
    from datetime import date

    if not months or not issue_date:
        return maturity
    y, m, d = (int(x) for x in issue_date.split("-"))
    t = date.fromisoformat(today)
    end = date.fromisoformat(maturity) if maturity else None
    while True:
        m += months
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        try:
            cand = date(y, m, d)
        except ValueError:
            cand = date(y, m, 28)
        if end and cand >= end:
            return end.isoformat()
        if cand > t:
            return cand.isoformat()


def usd_krw() -> float:
    """일 1회 기준 환율(ECB 기준, frankfurter.app). 실패하면 마지막 값 유지."""
    if _fx_cache.get("ts", 0) > time.time() - 3600:
        return _fx_cache["rate"]
    try:
        with urllib.request.urlopen("https://api.frankfurter.app/latest?from=USD&to=KRW", timeout=5) as resp:
            rate = float(json.loads(resp.read().decode())["rates"]["KRW"])
        _fx_cache.update(rate=rate, ts=time.time())
    except Exception:  # noqa: BLE001
        _fx_cache.setdefault("rate", 1400.0)
        _fx_cache["ts"] = time.time() - 3000
    return _fx_cache["rate"]
