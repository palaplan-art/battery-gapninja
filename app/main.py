import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware

from . import models  # noqa: F401  (imported so tables register on Base.metadata)
from .auth import SESSION_SECRET, is_authenticated, verify_credentials
from .database import Base, engine
from .routers import batteries, dashboard, machines

BASE_DIR = Path(__file__).resolve().parent.parent


def _auto_migrate() -> None:
    """Lightweight migration: create missing tables, then ADD any columns that
    exist on the models but not yet in the database. Handles both SQLite and
    Postgres so new nullable columns roll out on redeploy without manual DDL."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}')
                )


_auto_migrate()

app = FastAPI(title="Battery History Log")

# Session cookie: signed with SESSION_SECRET. https_only can be turned on in
# production (HTTPS) via SESSION_HTTPS_ONLY=1; kept off by default so local
# http testing works.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 12,  # 12 hours
    same_site="lax",
    https_only=os.environ.get("SESSION_HTTPS_ONLY", "").lower() in ("1", "true", "yes"),
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def require_auth(request: Request):
    """Dependency for API routes — returns 401 if the session is not logged in."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


app.include_router(batteries.router, dependencies=[Depends(require_auth)])
app.include_router(machines.router, dependencies=[Depends(require_auth)])
app.include_router(dashboard.router, dependencies=[Depends(require_auth)])


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    if verify_credentials(username, password):
        request.session["authenticated"] = True
        request.session["user"] = username
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password"},
        status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})
