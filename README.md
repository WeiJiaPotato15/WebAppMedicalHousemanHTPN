# Hospital Kajang Medical Houseman Roster

A web app that replaces the Google Sheet currently used by the Medical Department of Hospital Kajang to manage its weekly House Officer (HO) roster. Built for one HO leader to arrange the roster, multiple admins to amend it under sudden change, and every HO to see their schedule and posting stats without logging in.

> Public read-only roster view + Google-OAuth-gated admin editor + Plotly visualizations + AWS DynamoDB backend, hosted free on Streamlit Community Cloud.

## What it does

- **Public weekly roster** at the app URL. No login required (requirement #3).
- **Per-HO stats page** (also public, no login): days in posting, working hours so far, EL/MC used vs the 10-day cap, station mix.
- **Admin editor** with two views:
  - Spreadsheet grid (`st.data_editor`) — primary; familiar to current Google Sheets users; one shift code per (HO, day) cell.
  - Kanban-by-day — drag HO chips between shifts for a single day; useful during sudden re-arrangements.
- **Live multi-admin collaboration**: 5-second auto-refresh + presence indicator showing who else is editing.
- **Admin self-service**: admins manage other admins (super-admin only), house officer records, and the shift-code dictionary directly in the app.
- **Audit log**: every roster, officer, shift, and admin change is recorded with actor + timestamp.

## Architecture

```
   Anonymous viewer                   HO leader (Google account)
        │                                       │
        ▼                                       ▼
  ┌─────────────────────────────────────────────────────────┐
  │           Streamlit Community Cloud (free)              │
  │  streamlit_app.py  +  pages/*.py  +  lib/*.py           │
  └────────────┬───────────────────────┬────────────────────┘
               │                       │
               │ st.login("google")    │ boto3
               ▼                       ▼
        Google OAuth            AWS DynamoDB (free tier)
        (authorized emails)     hkj_roster, hkj_officers,
                                hkj_shifts, hkj_admins, hkj_audit
                                        │
                                        │ daily cron (GitHub Actions)
                                        ▼
                                AWS S3 (free tier) — JSON backups
```

Cost target: **USD 0.00/month** under realistic load. See [Cost section](#cost).

## Project layout

```
streamlit_app.py        # public entry point: weekly roster grid
pages/                  # 8 streamlit pages (HO Stats, Login, Edit Roster, Kanban, …)
lib/                    # shared modules: db (Memory + Dynamo backends), auth, viz, presence
infrastructure/         # boto3 scripts: tables, IAM policy, budget alarm
scripts/                # ops: seed shifts, import from gsheet, backup/restore S3
tests/                  # pytest, no AWS calls
.streamlit/             # config + secrets template
.github/workflows/      # CI lint+test, daily backup
```

## Local development (no AWS, no Google needed)

```powershell
git clone <this-repo>
cd WebAppMedicalHousemanHTPN
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

With no AWS credentials, the app falls back to an in-memory store seeded with the 37 shift codes and 3 sample HOs, so every page renders without setup. Auth pages will say Google OAuth isn't configured — that's expected.

Run tests:

```powershell
pip install -e ".[dev]"
pytest
```

## One-time setup for production

You need: an AWS account (free tier), a Google Cloud Platform project (free), a GitHub account, and a Streamlit Community Cloud account (free).

### 1. AWS — DynamoDB tables, IAM user, S3 bucket, Budget alarm

Follow `infrastructure/README.md`. Summary:

```bash
aws configure   # paste a temporary admin key
python infrastructure/create_tables.py        # creates 5 tables, provisioned 5/5 RCU/WCU each
aws s3 mb s3://hkj-roster-backups --region ap-southeast-1
aws s3api put-bucket-versioning --bucket hkj-roster-backups --versioning-configuration Status=Enabled
AWS_BUDGET_EMAIL=you@example.com python infrastructure/create_budget_alarm.py
```

Then in the AWS console: IAM → create user `hkj-roster-app` with the policy in `infrastructure/iam_policy.json`. Save its access key and secret — these go into Streamlit Cloud's Secrets UI, never into the repo.

### 2. Google OAuth (for admin login)

1. Go to https://console.cloud.google.com/apis/credentials.
2. Create / select a project.
3. **OAuth consent screen** → External → fill in app name, support email, developer email. Add yourself as a test user. Scopes: `openid`, `email`, `profile`.
4. **Credentials → Create credentials → OAuth client ID** → Application type **Web application**.
5. Authorized redirect URIs:
   - `http://localhost:8501/oauth2callback` (local dev)
   - `https://<your-app>.streamlit.app/oauth2callback` (after Streamlit Cloud assigns the URL)
6. Copy the client ID and client secret. They go into Streamlit Cloud's Secrets UI.

### 3. Streamlit Community Cloud

1. Push this repo to GitHub (must be **public** for the free tier — secrets are NOT in the repo, see `.gitignore`).
2. Go to https://share.streamlit.io and connect the repo.
3. In the app's **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example` after replacing every `REPLACE_WITH_*` placeholder with your real values:

```toml
[auth]
redirect_uri = "https://<your-app>.streamlit.app/oauth2callback"
cookie_secret = "<64-char hex>"
client_id = "<google client id>.apps.googleusercontent.com"
client_secret = "<google client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[aws]
region = "ap-southeast-1"
access_key_id = "<from IAM user hkj-roster-app>"
secret_access_key = "<from IAM user hkj-roster-app>"

[backup]
s3_bucket = "hkj-roster-backups"

[app]
disable_bootstrap = false
leave_cap = 10
leave_warn_at = 8
default_min_staff_per_ward = 1
```

4. Deploy. The first build takes ~2 minutes.

### 4. Claim the bootstrap admin

Visit your deployed URL → sidebar → **Login** → **Sign in with Google**. The very first Google login becomes the super-admin (`is_bootstrap=true`). The door auto-locks: any subsequent unknown email will be denied until you add them on the **Admins** page.

> **Tip**: be the first one to log in immediately after deploying. If anyone else gets there first, delete the bootstrap row from DynamoDB and re-claim, or set `disable_bootstrap=true` in secrets and add yourself manually.

### 5. Seed shift codes

If you used the in-memory store locally, the 37 codes are already seeded. For DynamoDB, run once with the IAM key in `.env`:

```bash
cp .env.example .env   # then fill in AWS_ACCESS_KEY_ID etc.
python scripts/seed_shifts.py
```

Or use the **"Seed default codes"** button on the Master Data page once logged in.

### 6. Import existing roster (optional)

Export your current Google Sheets weekly tab as CSV. Add the HOs first via the Officers page (so the import knows which name → email maps to which row), then:

```bash
python scripts/import_from_gsheet.py \
  --csv-url 'https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=...' \
  --week-start 2026-05-04 \
  --actor leader@example.com
```

### 7. GitHub Actions secrets (for daily backups)

In the GitHub repo → **Settings → Secrets and variables → Actions**, add:

- `AWS_REGION` = `ap-southeast-1`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — same IAM key as Streamlit Cloud
- `HKJ_BACKUP_BUCKET` = `hkj-roster-backups`

Daily cron `.github/workflows/backup.yml` runs at 01:00 MYT and uploads JSON dumps of every table.

## Operations

### Adding an admin

Super-admin: log in → **Admins** page → enter Google email → choose role → Add.
The added person can now log in with their Google account.

### Removing an admin

Super-admin: log in → **Admins** → click **Remove** next to the email.
A super-admin cannot remove themselves to prevent accidental lockout.

### Adjusting the leave cap

Edit `[app] leave_cap` in Streamlit Cloud's Secrets UI; restart the app from the Cloud panel.

### Restoring from backup

```bash
python scripts/restore_from_s3.py 2026-05-06            # all tables
python scripts/restore_from_s3.py 2026-05-06 --only hkj_roster
```

### Rotating IAM keys

Create a new access key for `hkj-roster-app` in IAM → paste into Streamlit Cloud secrets → restart app → delete the old key in IAM. Do the same in GitHub Actions secrets.

## Cost

| Resource | Free-tier ceiling | Realistic monthly use | Bill |
|---|---|---|---|
| Streamlit Community Cloud | unlimited public-app hosting | 1 app | $0 |
| DynamoDB provisioned | 25 RCU + 25 WCU + 25 GB (always free) | ~5 RCU peak, < 1 MB | $0 |
| S3 | 5 GB + 20K GET + 2K PUT/month (12 mo) | ~50 MB total, 5 PUT/day | $0 |
| Google OAuth | unlimited at free tier | < 100 logins/mo | $0 |
| AWS Budget alarms | 2 free | 1 used | $0 |

**Bot-flood scenario**: a scraper hammering the public page hits Streamlit's `@st.cache_data(ttl=10)` first; only ~6 DynamoDB reads/minute reach AWS regardless of bot RPS. If a bot somehow exceeds 25 RCU, requests are throttled (HTTP 400), not billed extra. Budget alarm catches anything else.

## Security

- **Source code is public.** Secrets must NEVER be committed. Use Streamlit Cloud's Secrets UI; `.gitignore` excludes `.streamlit/secrets.toml` and `.env`.
- **Bootstrap-once admin** — once the first super-admin claims, the door is locked and only that admin can grant access.
- **Audit log is append-only** in the app (no UI to delete rows; admins only read).
- **DynamoDB TLS** — boto3 uses TLS by default to all AWS APIs.
- **Cookie-based session** for OAuth — `cookie_secret` should be a random 64-char hex unique to the deployment.
- **No secrets in logs** — boto3 errors are caught and re-raised without echoing keys.

If you discover a vulnerability, do not file a public GitHub issue — email the bootstrap super-admin directly.

## Development notes

- Read paths in `lib/db.py` are wrapped at the page layer with `@st.cache_data(ttl=...)`. Writes call `st.cache_data.clear()` to ensure other admins see changes within the autorefresh interval.
- The `MemoryStore` is used automatically when AWS credentials are absent — convenient for offline dev and CI.
- All persistence goes through the `Store` ABC in `lib/db.py`; both backends pass the same tests.

## License

Internal use, Hospital Kajang Medical Department. Code is open for inspection but not licensed for redistribution without permission from the bootstrap super-admin.
