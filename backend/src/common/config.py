"""Runtime settings and secrets.

Secrets live in one Secrets Manager secret (JSON) whose ARN is passed as
SECRET_ARN. Locally you can set the same keys as environment variables.
"""
import json
import os

TABLE_NAME = os.environ.get("TABLE_NAME", "invest-desk-local")
SECRET_ARN = os.environ.get("SECRET_ARN", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", OWNER_EMAIL)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
WEB_SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL", "web_search_20250305")
KIS_BASE_URL = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
SITE_URL = os.environ.get("SITE_URL", "")

SECRET_KEYS = ("KIS_APP_KEY", "KIS_APP_SECRET", "ANTHROPIC_API_KEY", "DATA_GO_KR_KEY")


SECRET_TTL = 300  # 5분마다 다시 읽어 콘솔에서 바꾼 키를 반영
_cache: dict = {"values": None, "at": 0.0}


def secrets(refresh: bool = False) -> dict:
    import time

    if not refresh and _cache["values"] is not None and time.time() - _cache["at"] < SECRET_TTL:
        return _cache["values"]
    values = {k: os.environ.get(k, "") for k in SECRET_KEYS}
    if SECRET_ARN:
        import boto3

        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        stored = json.loads(raw or "{}")
        values.update({k: str(v).strip() for k, v in stored.items() if v and not str(v).startswith("CHANGE_ME")})
    _cache.update(values=values, at=time.time())
    return values


SECRET_HELP = {
    "KIS_APP_KEY": "한국투자증권 앱키",
    "KIS_APP_SECRET": "한국투자증권 앱시크릿",
    "ANTHROPIC_API_KEY": "Claude API 키",
    "DATA_GO_KR_KEY": "공공데이터포털 인증키",
}


def secret(name: str) -> str:
    value = secrets().get(name, "")
    if not value:  # 방금 입력했을 수 있으니 한 번 더 새로 읽는다
        value = secrets(refresh=True).get(name, "")
    if not value:
        raise RuntimeError(f"{SECRET_HELP.get(name, name)}({name})가 아직 입력되지 않았습니다. "
                           "AWS 콘솔(시드니) Secrets Manager의 AppSecret에 값을 넣어 주세요.")
    return value
