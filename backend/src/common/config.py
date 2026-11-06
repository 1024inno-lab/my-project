"""Runtime settings and secrets.

Secrets live in one Secrets Manager secret (JSON) whose ARN is passed as
SECRET_ARN. Locally you can set the same keys as environment variables.
"""
import json
import os
from functools import lru_cache

TABLE_NAME = os.environ.get("TABLE_NAME", "invest-desk-local")
SECRET_ARN = os.environ.get("SECRET_ARN", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", OWNER_EMAIL)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
WEB_SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL", "web_search_20250305")
KIS_BASE_URL = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
SITE_URL = os.environ.get("SITE_URL", "")

SECRET_KEYS = ("KIS_APP_KEY", "KIS_APP_SECRET", "ANTHROPIC_API_KEY", "DATA_GO_KR_KEY")


@lru_cache(maxsize=1)
def secrets() -> dict:
    values = {k: os.environ.get(k, "") for k in SECRET_KEYS}
    if SECRET_ARN:
        import boto3

        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        stored = json.loads(raw or "{}")
        values.update({k: v for k, v in stored.items() if v and not str(v).startswith("CHANGE_ME")})
    return values


def secret(name: str) -> str:
    value = secrets().get(name, "")
    if not value:
        raise RuntimeError(f"{name} 값이 비어 있습니다. Secrets Manager에 입력해 주세요.")
    return value
