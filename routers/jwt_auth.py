"""HW7 Part 1: JWT bearer authentication and role-based authorization.

Replaces the HW4 server-side session (still available at the hw4 tag) on the
/api/notices routes. Users live in the MySQL `users` table with bcrypt
password hashes and a role of reader, writer or moderator.

    POST /auth/login  form fields username + password -> {"access_token", "token_type"}
    GET  /auth/me     Authorization: Bearer <token>   -> {"id", "username", "role"}
"""
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db_session_basede26
from models import User
from routers.session_auth import verify_password

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ROLES = ("reader", "writer", "moderator")

router = APIRouter(prefix="/auth", tags=["jwt-auth"])
# OAuth2PasswordBearer answers 401 (not 403) when the Authorization header is missing.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(username: str, role: str) -> str:
    """Sign a JWT carrying the username (sub), role and an expiry time."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)
    payload = {"sub": username, "role": role, "exp": expires}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/login")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db_session_basede26: Session = Depends(get_db_session_basede26),
) -> dict:
    """Fetch the user from MySQL, verify the bcrypt hash, and only then issue a JWT."""
    user = db_session_basede26.query(User).filter(User.username == form.username).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": create_access_token(user.username, user.role), "token_type": "bearer"}


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db_session_basede26: Session = Depends(get_db_session_basede26),
) -> User:
    """Decode and check the bearer token, then load its user; any problem -> 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError as exc:  # bad signature, malformed or expired
        raise unauthorized from exc
    username = payload.get("sub")
    user = db_session_basede26.query(User).filter(User.username == username).first()
    if user is None:
        raise unauthorized
    return user


def require_roles(*allowed_roles: str) -> Callable[..., User]:
    """Dependency factory: valid token but a role outside allowed_roles -> 403."""

    def role_checker(user: User = Depends(get_current_user)) -> User:
        """Let the request through only for an allowed role."""
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' may not do this; requires {', '.join(allowed_roles)}",
            )
        return user

    return role_checker


@router.get("/me")
def read_me(user: User = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity and role."""
    return {"id": user.id, "username": user.username, "role": user.role}
