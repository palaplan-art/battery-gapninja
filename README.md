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

## Deploying to Render

This repo includes a `Dockerfile` and a `render.yaml` blueprint, so deployment is largely one click once the repo is on GitHub and connected to Render:

1. Push this project to a GitHub repository.
2. In the Render dashboard: **New +** → **Blueprint**, then select the GitHub repo. Render reads `render.yaml` and provisions the web service automatically.
3. During blueprint setup, Render prompts for the `ADMIN_PASSWORD` value (it is marked `sync: false`, so it is entered in the dashboard and never stored in this repo). Set it to your desired admin password.
4. `render.yaml` requests the **Starter** plan with a 1 GB persistent disk mounted at `/var/data`, and points `DATABASE_URL` at a SQLite file on that disk — this is what keeps `battery_log.db` from being wiped on every redeploy (Render's free tier has no persistent disk, so the database would reset on each deploy there).
5. Once deployed, Render gives an HTTPS URL (e.g. `https://gapninja-battery-log.onrender.com`) reachable from anywhere. Sign in with `admin` / the password you set.

The deployed database starts empty. Populate it either through the UI, or by running the bundled import script against the live URL (it logs in first, then posts the data).

If higher durability than a single-disk SQLite file is wanted later, swap `DATABASE_URL` to a Render-managed Postgres connection string — the app already runs on SQLAlchemy, so no code changes are needed beyond adding a Postgres driver (`psycopg2-binary`) to `requirements.txt`.
