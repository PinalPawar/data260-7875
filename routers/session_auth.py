"""
HW4 Part 2 auth: email+password login backed by a server-side session table.

This is deliberately separate from routers/auth.py (HW3's signed-cookie
Starlette session used by the "/", "/login", "/dashboard" template demo).
That HW3 cookie carries its payload (signed, not encrypted) inside the
cookie itself. HW4 asks for the opposite design: the cookie carries nothing
but a random, meaningless token; the real session record -- who it belongs
to and when it expires -- lives server-side in the `sessions` table and is
looked up on every request. Hence a separate cookie name (s7875_session)
and a separate router, so the two don't collide or get confused with each
other.
"""
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db_session_basede26
from models import SessionToken, User
from schemas import LoginPayload, RegisterPayload

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE_NAME = "s7875_session"   # PREFIX-scoped, distinct from HW3's "session" cookie
SESSION_TTL_MINUTES = 30


def hash_password(password: str) -> str:
    # bcrypt has a hard 72-byte input cap; truncate defensively rather than
    # letting a long password raise at login time.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))


def require_session(
    request: Request,
    db_session_basede26: Session = Depends(get_db_session_basede26),
) -> User:
    """
    Dependency used to protect the notice CRUD endpoints. Reads the opaque
    token from the cookie, looks up the matching row in `sessions`, checks
    it hasn't expired, and returns the logged-in User -- or raises 401,
    which the React app turns into the "Login required" state.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Login required")

    session_row = (
        db_session_basede26.query(SessionToken)
        .filter(SessionToken.id == token)
        .first()
    )
    if not session_row:
        raise HTTPException(status_code=401, detail="Login required")

    if session_row.expires_at < datetime.utcnow():
        db_session_basede26.delete(session_row)
        db_session_basede26.commit()
        raise HTTPException(status_code=401, detail="Session expired, please log in again")

    user = db_session_basede26.query(User).filter(User.id == session_row.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


@router.post("/register")
def register(payload: RegisterPayload, db_session_basede26: Session = Depends(get_db_session_basede26)):
    """
    Not required by the HW4 spec, but needed so there's a way to create a
    user with a real hashed password to log in with (rather than seeding
    one by hand). Kept intentionally simple.
    """
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db_session_basede26.add(user)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    db_session_basede26.refresh(user)
    return {"id": user.id, "name": user.name, "email": user.email}


@router.post("/login")
def login(
    payload: LoginPayload,
    response: Response,
    db_session_basede26: Session = Depends(get_db_session_basede26),
):
    user = db_session_basede26.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        # Same error for "no such user" and "wrong password" -- don't leak
        # which one it was.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = secrets.token_hex(32)  # opaque: unguessable, carries no meaning on its own
    expires = datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES)
    db_session_basede26.add(SessionToken(id=token, user_id=user.id, expires_at=expires))
    db_session_basede26.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,      # not readable by JS -- mitigates XSS token theft
        samesite="lax",     # blocks the cookie being sent on cross-site requests
        max_age=SESSION_TTL_MINUTES * 60,
    )
    return {"message": "logged in", "user": {"id": user.id, "name": user.name, "email": user.email}}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db_session_basede26: Session = Depends(get_db_session_basede26),
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session_row = db_session_basede26.query(SessionToken).filter(SessionToken.id == token).first()
        if session_row:
            db_session_basede26.delete(session_row)
            db_session_basede26.commit()
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"message": "logged out"}


@router.get("/me")
def me(user: User = Depends(require_session)):
    return {"logged_in": True, "id": user.id, "name": user.name, "email": user.email}
