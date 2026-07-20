import os
import secrets

from fastapi import Request

# Credentials come from environment variables so the real password is never
# committed to the repository. Defaults are for local development only —
# set ADMIN_PASSWORD (and ideally ADMIN_USERNAME) in the deployment environment.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# Signing key for the session cookie. A random per-process key is used if none is
# provided, which means restarting the server invalidates existing sessions —
# acceptable for local dev. Always set SESSION_SECRET in production.
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))


def verify_credentials(username: str, password: str) -> bool:
    username_ok = secrets.compare_digest(username or "", ADMIN_USERNAME)
    password_ok = secrets.compare_digest(password or "", ADMIN_PASSWORD)
    return username_ok and password_ok


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))
