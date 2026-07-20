# GAPNINJA Battery History Log

A web app for logging and tracking the service history of GAPNINJA batteries (GNB-0001, GNB-0002, ...).

## Features

- Search a battery by its last digits (type `1`, `0001`, or `GNB-0001`)
- Record/edit the machine a battery is assigned to (GN-001) and its End-User
- Commission date and last cell-replacement date pinned at the top of the detail page
- Battery health % computed from the last recorded capacity reading (mAh) against a 6000 mAh baseline
- Every change is logged automatically (machine change, end-user change, status change, cell replacement, capacity reading) — activity log entries can also be edited or deleted
- Machines are fully editable (customer, division, contact, phone, install date, remark) from a dedicated Machines view
- Dashboard for the Service team: counts by status, and a highlighted list of batteries that need attention (no cell change logged in over 180 days)
- Session-based admin login protecting the whole app (credentials supplied via environment variables — never hardcoded)

## Authentication

The app is protected by a single admin login. Credentials are read from environment variables so the password is never stored in the repository:

| Variable | Purpose | Default (local dev) |
|----------|---------|---------------------|
| `ADMIN_USERNAME` | Login username | `admin` |
| `ADMIN_PASSWORD` | Login password | `admin` |
| `SESSION_SECRET` | Signs the session cookie | random per process |
| `SESSION_HTTPS_ONLY` | Set to `1` when served over HTTPS | off |

Run locally with a chosen password:

```bash
# Windows PowerShell
$env:ADMIN_PASSWORD = "your-password"; uvicorn app.main:app --reload
```

On Render, `ADMIN_PASSWORD` is set in the dashboard (see below), so it never appears in this public repo.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` in a browser.

A SQLite database (`battery_log.db`) is created automatically at the project root on first run.

## Project structure

```
app/
  main.py        FastAPI app + mount static/templates
  database.py    SQLAlchemy engine/session
  models.py      Battery, Machine, BatteryLog
  schemas.py     Pydantic schemas
  crud.py        DB operations + auto-diff logging
  routers/       batteries.py, machines.py, dashboard.py
static/          css/js
templates/       index.html
```

## Deploying to Render (free tier + Neon Postgres)

Render's free web instances have no persistent disk, so the database lives in a
free external Postgres from [Neon](https://neon.tech) (persistent, non-expiring
free tier). The app runs on SQLAlchemy and auto-detects Postgres via `DATABASE_URL`.

1. **Create a free Neon database:** sign up at neon.tech → create a project → copy the
   **connection string** (looks like `postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require`).
2. **Deploy on Render:** **New +** → **Blueprint** → select this GitHub repo. Render reads
   `render.yaml` (free plan, no disk) and prompts for the two `sync: false` values:
   - `DATABASE_URL` → paste the Neon connection string
   - `ADMIN_PASSWORD` → your chosen admin password
3. Render builds the Docker image and deploys. On first boot the app creates its tables in Neon.
4. Open the HTTPS URL (e.g. `https://gapninja-battery-log.onrender.com`) and sign in with
   `admin` / your password.

> Free Render instances sleep after ~15 min of inactivity; the first request afterwards
> takes ~30–60s to wake. Data is safe in Neon regardless of sleeps or redeploys.

The deployed database starts empty. Populate it through the UI, or run the bundled import
script against the live URL (it logs in first, then posts the data over the API).

To run always-on with no cold starts instead, switch `render.yaml` to `plan: starter` and add
a `disk:` block with a SQLite `DATABASE_URL` — that is a paid Render plan (~$7/mo).
