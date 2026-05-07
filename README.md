# Hospital Tengku Permaisuri Norashikin — Medical Houseman Roster

A Streamlit web app that replaces the Google Sheet currently used by the Medical Department of Hospital Tengku Permaisuri Norashikin (HTPN) to manage its weekly House Officer (HO) roster. Built so one HO leader (or a small team of admins) can arrange and amend the roster under sudden change, while every HO and the public can see the published schedule and personal stats without an account.

> Public read-only roster + Google-OAuth-gated admin editor + Plotly visualisations + AWS DynamoDB backend, hosted free on Streamlit Community Cloud. Cost target USD 0/month at hospital scale.

---

## What the app does

### Public, no login

- **Overview** — weekly roster grid, one heatmap per ward group (W1, W2, W3, W6, then any others). Cells coloured by duty type. Hidden when the week is a draft.
- **HO Stats** — pick your name from a dropdown (HOs whose End-of-Posting was > 30 days ago are hidden so the list stays compact). Shows:
  - Days in posting · Average weekly hours over the last 4 weeks · EL/MC used vs the 10-day cap · Posting start date
  - Leave-cap gauge · Station-mix donut · Weekly hours trend line · EL/MC dates timeline + table

### Admin, after Google sign-in

- **Edit Roster** — spreadsheet grid (rows = HOs, columns = days of the chosen week). Each cell is a dropdown of all 37 shift codes. Changes save instantly, log to the audit table, and broadcast to other admins within 5 s via `streamlit-autorefresh`. Below the grid:
  - **Hours summary** — per-HO weekly hours, with yellow highlight for under-60h and red for over-64h.
  - **Staff per category per day** — pivot table; zero cells in critical wards / OC / PERI / MOPD / PENDING ED light up red (MOPD on weekends is exempt).
  - **Color preview** — Overview-style heatmap of the editor's current state.
  - **Plan ahead** — when a week has data and the next week doesn't, a button creates next week as a draft, carrying the same officer row order forward.
  - **Publish** — when viewing a draft, a button publishes it to the public.
  - **Coverage & hours preview charts** (Plotly).
- **Kanban view** — drag HO chips between shift columns for visual rebalancing of a single day. Saves on release.
- **Officers** — manage the HO master list. Two tables:
  - *Computed summary* — read-only Name / Ward / Posting # / Posting start / EOP date / MC/EL used (derived live).
  - *Edit profiles* — IC number is the primary key; ward group is a dropdown of W1, W2, W3, W6; posting number is a dropdown of 1st–6th.
- **Master Data** — add, rename, retire shift codes (Code, Hours, Duty type, Ward).
- **Admins** — super-admins manage the allowlist. Add/promote/demote/remove. Self-removal blocked.
- **Activity** — append-only audit log filtered by month, with actor + action filters.

### Workflow guards

- **Posting window** — admin cannot assign cells before an HO's `posting_start_date`. The HO's row only appears in the editor when their posting has started by week's end.
- **End-of-posting gate** — assigning a shift whose `duty_type` is `EOP` records that as the HO's End-of-Posting date (derived live, no separate field). Cells after EOP cannot be assigned, and any leftover post-EOP cells are auto-cleared on page render. HOs past EOP are dropped from the next-week template; HOs whose EOP was > 30 days ago disappear from the public HO Stats dropdown.
- **Hours band** — < 60 h yellow, 60–64 h accepted, > 64 h red. Banners list affected HOs.
- **Draft / publish** — weeks created via "Create roster for next week" (and any future week without an explicit template) are drafts, invisible to the public. Admin clicks **Publish** when the roster is ready. Past and current weeks without templates are implicitly published (back-compat).

---

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
               │ st.login("google")    │ boto3 (TLS)
               ▼                       ▼
        Google OAuth            AWS DynamoDB (free tier)
        (admin allowlist)       htpn_roster · htpn_officers
                                htpn_shifts · htpn_admins
                                htpn_audit
                                        │
                                        │ daily cron via GitHub Actions
                                        ▼
                                AWS S3 (free tier) — JSON backups
```

**Identity model**

- `Officer.ic_number` (Malaysian IC, no dashes) is the HO primary key.
- `Admin.email` is the admin's Google login. Two distinct identity spaces; the audit log records the admin's email as the actor.

---

## Project layout

```
streamlit_app.py            # Public Overview entry, builds st.navigation sidebar
pages/
  1_HO_Stats.py             # Public per-HO stats
  2_Login.py                # Google OAuth gate + bootstrap-claim button
  3_Edit_Roster.py          # Admin spreadsheet editor, presence, autorefresh
  4_Kanban_View.py          # Admin drag-drop view
  5_Officers.py             # Admin HO master list
  6_Master_Data.py          # Admin shift dictionary
  7_Admins.py               # Super-admin allowlist
  8_Activity.py             # Audit log viewer
lib/
  models.py                 # Pydantic models (Officer, Shift, Assignment, Admin, AuditEntry)
  db.py                     # Store ABC + MemoryStore (dev) + DynamoStore (prod) + factory
  auth.py                   # current_user / require_admin / require_super / login button
  viz.py                    # Plotly figure builders + week_grid_figure helper
  presence.py               # In-memory heartbeat for "who else is editing"
  constants.py              # SEED_SHIFTS, WARD_GROUPS, DUTY_COLORS, leave/hour thresholds
infrastructure/
  create_tables.py          # boto3 idempotent table creator (5 tables, 5/5 RCU/WCU each)
  create_budget_alarm.py    # USD 1/month budget alarm
  iam_policy.json           # Least-privilege policy for the app's IAM user
  README.md                 # AWS account prep walkthrough
scripts/
  seed_shifts.py            # Insert the 37 shift codes
  import_from_gsheet.py     # Bulk-import an existing weekly tab (CSV)
  backup_to_s3.py           # JSON dump of every table
  restore_from_s3.py        # Restore from a chosen S3 backup key
tests/                      # pytest, no AWS calls — 25 tests
.streamlit/                 # config.toml + secrets.toml.example (real one is gitignored)
.github/workflows/          # lint+pytest CI, daily backup cron
requirements.txt            # streamlit[auth] + httpx + boto3 + pandas + plotly + pydantic + …
pyproject.toml
```

---

## Local development (no AWS, no Google needed)

```powershell
git clone <this-repo>
cd WebAppMedicalHousemanHTPN
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Without AWS credentials the app falls back to an **in-memory store** seeded with the 37 shift codes plus three sample HOs (Dr. Alice/W1/1st posting, Dr. Ben/W2/3rd, Dr. Chen/W3/2nd) and a week of sample assignments. Every page renders without setup. Login pages show a friendly "OAuth not configured" banner.

To run the tests:

```powershell
pip install -e ".[dev]"
pytest
```

---

## Production setup

You need: an AWS account (free tier is sufficient), a Google Cloud Platform project (free), a public GitHub repo, and a Streamlit Community Cloud account (free).

### 1. AWS resources

See `infrastructure/README.md` for the long form. Short form:

```powershell
aws configure                                            # paste a temporary admin key
.venv\Scripts\python.exe infrastructure\create_tables.py # 5 DynamoDB tables, 5/5 RCU/WCU
aws s3 mb s3://htpn-roster-backups --region ap-southeast-1
aws s3api put-bucket-versioning --bucket htpn-roster-backups --versioning-configuration Status=Enabled
$env:AWS_BUDGET_EMAIL = "you@example.com"
.venv\Scripts\python.exe infrastructure\create_budget_alarm.py
```

In the AWS Console: **IAM → Users → Create user `htpn-roster-app`**, attach `infrastructure/iam_policy.json` as a custom policy, generate an access key (Application running outside AWS). The key/secret go into Streamlit Cloud's Secrets UI, never the repo.

### 2. Google OAuth

1. https://console.cloud.google.com → create project (`htpn-roster`).
2. **APIs & Services → OAuth consent screen** → External → fill in name/support email/developer email. Add yourself + co-admin emails as **Test users**.
3. **Credentials → Create Credentials → OAuth client ID** → Web application.
4. Add Authorized redirect URIs:
   - `http://localhost:8501/oauth2callback` (local dev)
   - `https://<your-app>.streamlit.app/oauth2callback` (deployed; come back and edit once Cloud assigns the URL)
5. Save the Client ID and Client secret.

### 3. Streamlit Community Cloud

1. Push this repo to GitHub (must be **public** for the free tier — secrets are gitignored).
2. https://share.streamlit.io → connect the repo → main file `streamlit_app.py` → Deploy.
3. After deploy, **Settings → Secrets** → paste:

```toml
[auth]
redirect_uri  = "https://<your-app>.streamlit.app/oauth2callback"
cookie_secret = "<64-char hex; python -c 'import secrets; print(secrets.token_hex(32))'>"

[auth.google]
client_id           = "<from GCP>.apps.googleusercontent.com"
client_secret       = "<from GCP>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[aws]
region            = "ap-southeast-1"
access_key_id     = "<from htpn-roster-app IAM user>"
secret_access_key = "<from htpn-roster-app IAM user>"

[backup]
s3_bucket = "htpn-roster-backups"

[app]
disable_bootstrap          = false
leave_cap                  = 10
leave_warn_at              = 8
default_min_staff_per_ward = 1
```

4. Click **Reboot**. First build takes ~2 minutes.

### 4. Claim the bootstrap admin

Visit your app URL → sidebar → **Login** → **Sign in with Google**. The very first Google login is auto-promoted to `super` admin. The door auto-locks immediately — any later unknown email is denied until the super-admin adds them on the **Admins** page.

> **Tip**: deploy when nobody else is around, and be the first to log in. If someone gets there first, delete the bootstrap row from `htpn_admins` in DynamoDB and re-claim, or set `[app] disable_bootstrap = true` in secrets and add yourself manually.

### 5. Seed shift codes (production only)

Locally with AWS keys in `.env`:

```powershell
copy .env.example .env   # then fill in AWS keys + region
.venv\Scripts\python.exe scripts\seed_shifts.py
```

Or click **Master Data → Seed default codes from Grouping sheet** in the deployed app.

### 6. Import existing roster (optional, one-shot)

Add the HOs first via the Officers page (the import matches by name → IC number). Then export your weekly Google Sheets tab as CSV and:

```powershell
.venv\Scripts\python.exe scripts\import_from_gsheet.py `
  --csv-url 'https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=...' `
  --week-start 2026-05-04 `
  --actor leader@example.com
```

### 7. GitHub Actions secrets (for nightly backups)

Repo **Settings → Secrets and variables → Actions** → add:

- `AWS_REGION`            → `ap-southeast-1`
- `AWS_ACCESS_KEY_ID`     → same IAM user's key
- `AWS_SECRET_ACCESS_KEY` → same IAM user's secret
- `HTPN_BACKUP_BUCKET`    → `htpn-roster-backups`

`.github/workflows/backup.yml` runs daily at 17:00 UTC (01:00 MYT) and uploads JSON dumps under `s3://htpn-roster-backups/backups/<YYYY-MM-DD>/<table>.json`.

---

## Day-to-day operations

### Build next week's roster (typical flow)

1. Edit Roster → navigate to current week → click **➕ Create roster for next week**.
2. The page jumps to next week. The header shows **📝 DRAFT — not visible to public**. The grid is blank but rows match the current week's officer ordering (HOs past EOP are dropped automatically).
3. Fill cells. The Hours summary, Staff-per-category, and Color preview update live.
4. When ready, click **✅ Publish this week** at the bottom.

### Mark an HO's End of Posting

Assign the **EOP** shift code on their last day. The Officers page picks it up as their EOP date automatically; further cells on later days are blocked; the HO is dropped from future weeks' templates and disappears from public HO Stats 30 days after the EOP date.

### Add a new admin

Super-admin → **Admins** → enter Google email → choose `admin` or `super` → **Add**. The new admin can sign in immediately.

### Adjust the leave cap

Streamlit Cloud → **Settings → Secrets** → change `[app] leave_cap` → **Reboot**.

### Restore from backup

```powershell
.venv\Scripts\python.exe scripts\restore_from_s3.py 2026-05-06              # all tables
.venv\Scripts\python.exe scripts\restore_from_s3.py 2026-05-06 --only htpn_roster
```

### Rotate the IAM key

IAM Console → create a second access key for `htpn-roster-app` → paste it into Streamlit Cloud Secrets and into GitHub Actions secrets → reboot the app → confirm everything still works → delete the old key.

---

## Cost

| Resource | Free-tier ceiling | Realistic monthly use | Bill |
|---|---|---|---|
| Streamlit Community Cloud | unlimited public-app hosting | 1 app | $0 |
| DynamoDB provisioned | 25 RCU + 25 WCU + 25 GB (always free) | ~5 RCU peak, < 1 MB | $0 |
| S3 | 5 GB + 20K GET + 2K PUT/month (12 mo) | ~50 MB total, ≤ 5 PUT/day | $0 |
| Google OAuth | unlimited at free tier | < 100 logins/mo | $0 |
| AWS Budget alarms | 2 free | 1 used | $0 |

**Bot-flood scenario**: a scraper hammering the public page hits Streamlit's `@st.cache_data(ttl=10)` first; only ~6 DynamoDB reads/minute reach AWS regardless of bot RPS. If a bot somehow exceeds 25 RCU, requests are throttled (HTTP 400 ProvisionedThroughputExceededException), not billed extra. The Budget alarm catches anything else.

---

## Security

- **Source code is public.** Secrets MUST never be committed. `.gitignore` excludes `.streamlit/secrets.toml`, `.env`, and AWS credential files. Real values live in Streamlit Cloud's Secrets UI and GitHub Actions Secrets.
- **Bootstrap-once admin** — the first Google login becomes super-admin; the door auto-locks for everyone else.
- **Append-only audit log** — every roster, officer, shift, admin, and template change records actor + timestamp + before/after. There is no UI to delete audit rows.
- **Posting window enforcement** — assignments outside `[posting_start_date, eop_date]` are rejected on save and auto-cleared on render.
- **Draft gate** — future weeks are drafts by default; nothing reaches the public Overview or HO Stats until an admin clicks Publish.
- **Cookie-secret rotation** — `cookie_secret` should be a random 64-char hex unique to your deployment. Rotate by generating a new one in Cloud Secrets and rebooting; existing admin sessions are invalidated on the next request.
- **DynamoDB TLS** — boto3 uses TLS by default; the IAM policy in `infrastructure/iam_policy.json` is least-privilege (only the 5 tables and the backup bucket).

If you find a vulnerability, do not file a public GitHub issue — email the bootstrap super-admin directly.

---

## Development notes

- The `Store` ABC in `lib/db.py` exposes a single interface; `MemoryStore` and `DynamoStore` both pass the test suite.
- The factory `get_store()` checks `[aws]` secrets and env vars; values starting with `REPLACE_WITH_*` are treated as unfilled placeholders so the dev path stays on `MemoryStore` even when secrets.toml exists with template values.
- Pages wrap reads with `@st.cache_data(ttl=…)` and call `st.cache_data.clear()` after every write so collaborators see edits within the 5-second autorefresh.
- All persistence goes through `Store`. There is no direct `boto3` call from any page module.
- The week template (`pk = WEEK#<monday>`, `sk = TEMPLATE`) coexists with assignment rows in `htpn_roster` because the assignment scan filters `sk` by ISO date range and the templates use `sk = "TEMPLATE"`.

---

## License

Internal use, Hospital Tengku Permaisuri Norashikin Medical Department. Code is open for inspection but not licensed for redistribution without permission from the bootstrap super-admin.
