"""Single-table DynamoDB access. Every item is {pk, sk, data(json string)}.

Key layout
  HOLDING            / <id>          보유 종목 (stock | bond | irp)
  CONTRIB            / <date>#<id>   IRP 납입 기록
  TRADE              / <date>#<id>   주식 매매 기록 (실현손익)
  SETTINGS           / main          운용 원칙·IRP 목표 등
  STRATEGY           / <YYYY-MM-DD>  데일리 전략 결과 (화면 표시용)
  JUDGMENT           / <YYYY-MM-DD>  종목별 요인 신호·판단 (복기용, 화면 비노출)
  REVIEW             / <YYYY-MM-DD>  복기 결과 (화면 비노출)
  MODEL              / weights       현재 요인 가중치 (화면 비노출)
  MODEL              / log#<date>    가중치 조정 이력 (화면 비노출)
  CACHE              / kis-token     KIS 접근 토큰
"""
import json
import time
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _table():
    import boto3

    return boto3.resource("dynamodb").Table(config.TABLE_NAME)


def put(pk: str, sk: str, data, ttl: int | None = None) -> None:
    item = {"pk": pk, "sk": sk, "data": json.dumps(data, ensure_ascii=False), "updatedAt": int(time.time())}
    if ttl:
        item["ttl"] = ttl
    _table().put_item(Item=item)


def get(pk: str, sk: str, default=None):
    item = _table().get_item(Key={"pk": pk, "sk": sk}).get("Item")
    return json.loads(item["data"]) if item else default


def delete(pk: str, sk: str) -> None:
    _table().delete_item(Key={"pk": pk, "sk": sk})


def query(pk: str, prefix: str | None = None, newest_first: bool = False, limit: int | None = None) -> list:
    from boto3.dynamodb.conditions import Key

    cond = Key("pk").eq(pk)
    if prefix:
        cond = cond & Key("sk").begins_with(prefix)
    kwargs = {"KeyConditionExpression": cond, "ScanIndexForward": not newest_first}
    if limit:
        kwargs["Limit"] = limit
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        resp = _table().query(**kwargs)
        items.extend(resp.get("Items", []))
        start = resp.get("LastEvaluatedKey")
        if not start or (limit and len(items) >= limit):
            break
    return [dict(json.loads(i["data"]), _sk=i["sk"]) for i in items]
