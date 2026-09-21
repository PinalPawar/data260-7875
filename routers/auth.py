"""
Login / session routes for the Grocery Recall Notices app (DATA260 HW3, Part 1).

Kept separate from main.py on purpose (assignment requirement: routes handled
in their own router).

Security notes for the report:
- Starlette's SessionMiddleware stores the session as a SIGNED cookie (not a
  server-side store). That means logging out on the server does NOT, by
  itself, make an old copy of the cookie stop working -- if someone captured
  the raw cookie value before logout, it would still decode successfully
  after logout, because the signature is still valid.
- To make "logged out" / "expired" actually mean something, every login gets
  a random one-time session id (`sid`). Logging out (or an idle timeout)
  adds that `sid` to a server-side blocklist (`REVOKED_SIDS`). Every
  protected request checks the blocklist, not just "is there a user in the
  cookie". That's what lets us *prove* a reused old session cookie fails.
"""

import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_302_FOUND

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Demo credentials only. In a real app these would live in a database with
# hashed (bcrypt) passwords, not a hardcoded string.
VALID_USERNAME = os.getenv("DEMO_USERNAME", "admin")
VALID_PASSWORD = os.getenv("DEMO_PASSWORD", "password")

# How many seconds a session may sit idle before it's treated as expired.
# Overridable via env var so it's easy to shrink for a demo/screenshot,
# e.g. `IDLE_TIMEOUT_SECONDS=15 python3 main.py`.
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "300"))

# Server-side blocklist of session ids that have been logged out or expired.
# This is what makes logout/expiry real instead of just cosmetic.
REVOKED_SIDS: set[str] = set()


def _session_status(request: Request):
    """
    Returns ("ok", username) if the session is valid and not idle-timed-out.
    Otherwise returns ("no_session" | "logged_out" | "expired", None).
    On success, also slides the idle window forward (updates last_seen).
    """
    user = request.session.get("user")
    sid = request.session.get("sid")
    last_seen = request.session.get("last_seen")

    if not user or not sid:
        return "no_session", None

    if sid in REVOKED_SIDS:
        return "logged_out", None

    if last_seen is not None and (time.time() - last_seen) > IDLE_TIMEOUT_SECONDS:
        REVOKED_SIDS.add(sid)
        request.session.clear()
        return "expired", None

    request.session["last_seen"] = time.time()
    return "ok", user


@router.get("/")
def home(request: Request, logged_out: Optional[str] = None):
    """
    Home page. Shows a Login link if nobody is logged in, or a
    Dashboard/Logout link if someone is. Shows a "logged out" confirmation
    banner when redirected here right after /logout.
    """
    _status, user = _session_status(request)
    return templates.TemplateResponse(
        "home.html", {"request": request, "user": user, "logged_out": logged_out}
    )


@router.get("/login")
def login_page(request: Request, expired: Optional[str] = None):
    """Displays the login form, with a Bootstrap alert if we got redirected here
    because an idle session expired."""
    error = "Your session timed out from inactivity. Please log in again." if expired else None
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """
    Validates the submitted credentials.
    - Correct: start a new session (fresh sid + timestamp), redirect to dashboard.
    - Wrong: re-render the login page with a Bootstrap alert (no redirect, so
      the error is easy to screenshot).
    """
    if username == VALID_USERNAME and password == VALID_PASSWORD:
        request.session["user"] = username
        request.session["sid"] = str(uuid.uuid4())
        request.session["last_seen"] = time.time()
        return RedirectResponse(url="/dashboard", status_code=HTTP_302_FOUND)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password."},
        status_code=401,
    )


@router.get("/dashboard")
def dashboard(request: Request):
    """
    Protected route. Only reachable with a valid, non-idle, non-revoked
    session -- otherwise bounces back to /login.
    """
    status, user = _session_status(request)
    if status == "expired":
        return RedirectResponse(url="/login?expired=1", status_code=HTTP_302_FOUND)
    if status != "ok":
        return RedirectResponse(url="/login", status_code=HTTP_302_FOUND)

    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})


@router.get("/logout")
def logout(request: Request):
    """Revokes the current session id (server-side), clears the cookie's contents,
    and redirects to the home page (per assignment spec: logout returns to /)."""
    sid = request.session.get("sid")
    if sid:
        REVOKED_SIDS.add(sid)
    request.session.clear()
    return RedirectResponse(url="/?logged_out=1", status_code=HTTP_302_FOUND)
