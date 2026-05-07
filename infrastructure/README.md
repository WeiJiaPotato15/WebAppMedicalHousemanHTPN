# Infrastructure setup (one-time, ~15 minutes)

You need a free-tier AWS account. After this you should have:

- 5 DynamoDB tables in `ap-southeast-1` (Singapore), provisioned at 5 RCU / 5 WCU each (total 25/25 — fully inside the always-free tier).
- 1 IAM user `hkj-roster-app` with the policy in `iam_policy.json` (least privilege).
- 1 S3 bucket `hkj-roster-backups` (versioning enabled).
- 1 AWS Budget alarm at USD 1/month, emailing you if anything ever charges.

## 0. Prerequisites

```bash
pip install boto3
aws configure   # paste root or a temporary admin key, region ap-southeast-1
```

For the long-term IAM key (used by the app), do not use root. Create the dedicated user below.

## 1. IAM user for the app

In the AWS console: **IAM → Users → Create user `hkj-roster-app`**, then:

- Attach policy → **Create policy** → JSON → paste `iam_policy.json` → name it `hkj-roster-app-policy`.
- Create access key (Application running outside AWS) → save the `Access key ID` and `Secret access key`. **Paste these into Streamlit Cloud's Secrets UI under `[aws]`** — never into the repo.

## 2. Create the DynamoDB tables

```bash
python infrastructure/create_tables.py --dry-run   # preview
python infrastructure/create_tables.py             # actually create
```

Idempotent — re-running skips tables that already exist.

## 3. Create the S3 backup bucket

```bash
aws s3 mb s3://hkj-roster-backups --region ap-southeast-1
aws s3api put-bucket-versioning \
  --bucket hkj-roster-backups \
  --versioning-configuration Status=Enabled
```

## 4. Create the budget alarm

```bash
AWS_BUDGET_EMAIL=you@example.com python infrastructure/create_budget_alarm.py
```

You'll get an email asking you to confirm the SNS subscription — click it.

## 5. Verify

- DynamoDB console → Tables: 5 tables visible, status ACTIVE, all in `ap-southeast-1`.
- IAM → Users → `hkj-roster-app` → Permissions: only `hkj-roster-app-policy` attached.
- S3 → Buckets: `hkj-roster-backups` exists.
- Billing → Budgets: 1 budget at USD 1.00, notifies your email.

## Cost guarantee

With:

- DynamoDB **provisioned** at 25 RCU / 25 WCU total (always-free tier),
- `@st.cache_data(ttl=...)` on every read in the app,
- on-demand mode disabled,

a bot hammering the public roster page can at most cause **throttled requests** (HTTP 400 ProvisionedThroughputExceededException), never an extra bill. The Budget alarm catches anything we missed.

## Tearing down

```bash
for t in hkj_roster hkj_officers hkj_shifts hkj_admins hkj_audit; do
  aws dynamodb delete-table --table-name "$t" --region ap-southeast-1
done
aws s3 rb s3://hkj-roster-backups --force --region ap-southeast-1
aws budgets delete-budget --account-id $(aws sts get-caller-identity --query Account --output text) --budget-name hkj-roster-monthly-1usd
```
