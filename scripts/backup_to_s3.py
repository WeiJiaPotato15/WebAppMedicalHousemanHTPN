"""Daily backup: dump every DynamoDB table as JSON, upload to S3.

Designed to be run by GitHub Actions on a cron (see .github/workflows/backup.yml).
Object key: backups/<YYYY-MM-DD>/<table>.json

Usage:
    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
    HTPN_BACKUP_BUCKET=htpn-roster-backups \
    python scripts/backup_to_s3.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

REGION = os.getenv("AWS_REGION", "ap-southeast-1")
BUCKET = os.getenv("HTPN_BACKUP_BUCKET", "htpn-roster-backups")
TABLES = ("htpn_roster", "htpn_officers", "htpn_shifts", "htpn_admins", "htpn_audit")


def _decimal_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError


def dump_table(ddb, name: str) -> list[dict]:
    items: list[dict] = []
    last_eval = None
    while True:
        kwargs: dict = {}
        if last_eval:
            kwargs["ExclusiveStartKey"] = last_eval
        resp = ddb.Table(name).scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_eval = resp.get("LastEvaluatedKey")
        if not last_eval:
            break
    return items


def main() -> int:
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        print("ERROR: AWS_ACCESS_KEY_ID not set.", file=sys.stderr)
        return 1
    ddb = boto3.resource("dynamodb", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)
    today = date.today().isoformat()
    failures = 0
    for t in TABLES:
        try:
            items = dump_table(ddb, t)
            body = json.dumps(items, default=_decimal_default).encode("utf-8")
            key = f"backups/{today}/{t}.json"
            s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json")
            print(f"  ✓ {t}: {len(items)} items → s3://{BUCKET}/{key}")
        except ClientError as e:
            print(f"  ✗ {t}: {e}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
