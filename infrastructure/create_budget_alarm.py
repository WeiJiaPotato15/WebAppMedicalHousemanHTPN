"""Create an AWS Budget alarm at USD 1.00/month so any unexpected cost emails you.

Free. Targets the whole account (you can scope to tags if you want, but for a
single-project account the simplest thing is to alarm on all spend).

Usage:
    AWS_BUDGET_EMAIL=you@example.com python infrastructure/create_budget_alarm.py
"""
from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError

BUDGET_NAME = "hkj-roster-monthly-1usd"


def main() -> int:
    email = os.getenv("AWS_BUDGET_EMAIL")
    if not email:
        print("Set AWS_BUDGET_EMAIL=you@example.com first.", file=sys.stderr)
        return 1

    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]

    budgets = boto3.client("budgets", region_name="us-east-1")  # Budgets is global, served via us-east-1

    budget = {
        "BudgetName": BUDGET_NAME,
        "BudgetLimit": {"Amount": "1.0", "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
    }
    notifications = [{
        "Notification": {
            "NotificationType": "ACTUAL",
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": 1.0,
            "ThresholdType": "ABSOLUTE_VALUE",
            "NotificationState": "ALARM",
        },
        "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}],
    }]

    try:
        budgets.create_budget(
            AccountId=account_id,
            Budget=budget,
            NotificationsWithSubscribers=notifications,
        )
        print(f"Created budget {BUDGET_NAME} for account {account_id} → notifies {email}")
    except budgets.exceptions.DuplicateRecordException:
        print(f"Budget {BUDGET_NAME} already exists. Updating notification subscriber…")
        budgets.update_subscriber(
            AccountId=account_id,
            BudgetName=BUDGET_NAME,
            Notification=notifications[0]["Notification"],
            OldSubscriber={"SubscriptionType": "EMAIL", "Address": email},
            NewSubscriber={"SubscriptionType": "EMAIL", "Address": email},
        )
    except ClientError as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
