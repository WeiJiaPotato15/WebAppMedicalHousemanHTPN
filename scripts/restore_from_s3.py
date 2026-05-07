"""Restore a chosen daily backup from S3 back into DynamoDB.

DESTRUCTIVE: overwrites items with the backed-up versions. Use after a bad write
or accidental mass change. Always make a fresh backup before restoring.

Usage:
    HTPN_BACKUP_BUCKET=htpn-roster-backups \
    python scripts/restore_from_s3.py 2026-05-06
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

REGION = os.getenv("AWS_REGION", "ap-southeast-1")
BUCKET = os.getenv("HTPN_BACKUP_BUCKET", "htpn-roster-backups")
TABLES = ("htpn_roster", "htpn_officers", "htpn_shifts", "htpn_admins", "htpn_audit")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("date", help="Backup date, YYYY-MM-DD")
    p.add_argument("--only", nargs="*", help="Restore only these tables (default: all)")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = p.parse_args()

    targets = list(args.only) if args.only else list(TABLES)
    if not args.yes:
        ans = input(f"Will restore {targets} from s3://{BUCKET}/backups/{args.date}/ — type 'yes': ")
        if ans.strip().lower() != "yes":
            print("Aborted.")
            return 1

    ddb = boto3.resource("dynamodb", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)
    for t in targets:
        key = f"backups/{args.date}/{t}.json"
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=key)
        except s3.exceptions.NoSuchKey:
            print(f"  ✗ {t}: backup not found at s3://{BUCKET}/{key}", file=sys.stderr)
            continue
        items = json.loads(obj["Body"].read())
        table = ddb.Table(t)
        with table.batch_writer() as bw:
            for it in items:
                bw.put_item(Item=it)
        print(f"  ✓ {t}: restored {len(items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
