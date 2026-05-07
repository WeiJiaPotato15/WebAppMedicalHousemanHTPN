"""Create the 5 DynamoDB tables in provisioned mode at the always-free 25/25 RCU/WCU.

Idempotent: re-running on existing tables is a no-op (it logs and skips).
Cost: stays inside the AWS Always Free tier (25 RCU + 25 WCU + 25 GB shared
across all tables in the account, in any region).

Usage:
    python infrastructure/create_tables.py [--region ap-southeast-1] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

DEFAULT_REGION = os.getenv("AWS_REGION", "ap-southeast-1")

# (table_name, partition_key, sort_key)
TABLES: list[tuple[str, str, str]] = [
    ("htpn_roster", "pk", "sk"),     # pk=HO#<email>, sk=<YYYY-MM-DD>
    ("htpn_officers", "pk", "sk"),   # pk=HO#<email>, sk="PROFILE"
    ("htpn_shifts", "pk", "sk"),     # pk=SHIFT#<code>, sk="MASTER"
    ("htpn_admins", "pk", "sk"),     # pk=ADMIN#<email>, sk="MASTER"
    ("htpn_audit", "pk", "sk"),      # pk=AUDIT#<YYYY-MM>, sk=<ts>#<actor>
]

# Note on capacity: Free tier is 25 RCU + 25 WCU shared across the account.
# We split it as 5 RCU / 5 WCU per table — well within the cap; can rebalance later.
PER_TABLE_RCU = 5
PER_TABLE_WCU = 5

TAGS = [{"Key": "Project", "Value": "htpn-roster"}]


def existing_tables(client) -> set[str]:
    out = set()
    paginator = client.get_paginator("list_tables")
    for page in paginator.paginate():
        out.update(page.get("TableNames", []))
    return out


def create_one(client, name: str, pk: str, sk: str, dry_run: bool) -> None:
    print(f"  - Creating {name} (pk={pk}, sk={sk}, {PER_TABLE_RCU} RCU / {PER_TABLE_WCU} WCU)")
    if dry_run:
        return
    client.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": pk, "AttributeType": "S"},
            {"AttributeName": sk, "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": pk, "KeyType": "HASH"},
            {"AttributeName": sk, "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={
            "ReadCapacityUnits": PER_TABLE_RCU,
            "WriteCapacityUnits": PER_TABLE_WCU,
        },
        Tags=TAGS,
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=name)


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    client = boto3.client("dynamodb", region_name=args.region)
    print(f"Region: {args.region}")
    print(f"Mode  : provisioned, {PER_TABLE_RCU} RCU / {PER_TABLE_WCU} WCU per table "
          f"(account total {PER_TABLE_RCU * len(TABLES)} RCU / "
          f"{PER_TABLE_WCU * len(TABLES)} WCU — under the 25/25 free tier).")
    if args.dry_run:
        print("(dry-run — no changes will be made)\n")

    existing = existing_tables(client)
    print(f"Existing tables in account: {sorted(existing) or '(none)'}")
    print("\nPlanned tables:")
    for name, pk, sk in TABLES:
        if name in existing:
            print(f"  · {name} — already exists, skipping")
            continue
        try:
            create_one(client, name, pk, sk, args.dry_run)
        except ClientError as e:
            print(f"  ! {name}: {e}", file=sys.stderr)
            return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
