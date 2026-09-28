import os

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

from sqlalchemy import event

from routers.auth import router as auth_router
from routers.session_auth import router as session_auth_router, require_session
from routers.n1_demo import router as n1_demo_router
from database import Base, engine, get_db_session_basede26
import crud
import schemas
import query_counter
from models import User

# HW4 Part 3: counts how many SQL statements MySQL actually executes during
# one request, so list-naive vs list-fixed can be measured honestly instead
# of just asserted. See query_counter.py for why this is a thread-local
# counter read inside the endpoint, not response-header/middleware based.
@event.listens_for(engine, "before_cursor_execute")
def _count_sql_queries(conn, cursor, statement, parameters, context, executemany):
    query_counter.increment()

app = FastAPI(title="Grocery Recall Notices API")

# HW4 Part 2: create notices/related_info/users/sessions tables in MySQL
# (s7875_rel) if they don't exist yet. Safe to call every startup.
Base.metadata.create_all(bind=engine)

# React dev server (Vite) origin. allow_credentials=True is required for the
# browser to send/receive the HttpOnly session cookie on cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HW3 Part 1: session support -------------------------------------------
# Secret key used to SIGN the session cookie (not encrypt it -- the contents
# are readable if someone really wants to base64-decode them, but they can't
# be *forged* or *tampered with* without knowing this key).
# In real deployment this must come from an environment variable, never be
# hardcoded/committed -- the fallback here is only so the app still runs
# out of the box for local grading.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-key-change-me")

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=True,   # "Secure" cookie flag -- browser will only send this over HTTPS
    same_site="lax",   # "SameSite" cookie flag -- blocks the cookie being sent cross-site
    max_age=3600,       # absolute cap: cookie itself dies after 1 hour no matter what
    # Note: HttpOnly is always on for Starlette's SessionMiddleware (not configurable) --
    # that's the 3rd of the 3 required Set-Cookie attributes.
)

# Auth routes (/, /login, /logout, /dashboard) live in their own router --
# this is the HW3 signed-cookie template demo, unchanged.
app.include_router(auth_router)

# HW4 email+password / opaque-session-token auth used by the React client
# and by the protected /api/notices endpoints below.
app.include_router(session_auth_router)

# HW4 Part 3: /api/notices/list-naive and /api/notices/list-fixed
app.include_router(n1_demo_router)


@app.get("/notices")
def notices_app():
    """
    The original HW1/HW2 recall-notices single-page app (unchanged).
    Moved from "/" to "/notices" so "/" can be the new HW3 login-aware
    home page (see routers/auth.py) -- this does NOT affect the separate
    Nginx/Docker static-hosting path from HW1, which serves index.html
    directly off disk and never goes through this file.
    """
    return FileResponse("index.html")

# --- HW4 Part 2: domain entity CRUD, backed by MySQL, gated on login ------
# All five endpoints below depend on require_session: an anonymous request
# gets a 401 with "Login required" before any DB query runs, which is what
# lets the React app show "Login required" / hide "Add Record" instead of
# silently returning data to a logged-out user.

@app.get("/api/notices", response_model=List[schemas.NoticeOut])
def get_notices(
    q: Optional[str] = None,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    records = crud.list_notices(db_session_basede26)
    if q:
        q_lower = q.lower()
        records = [
            n for n in records
            if q_lower in n.product.lower() or q_lower in n.manufacturer.lower()
        ]
    return records

@app.get("/api/notices/{notice_id}", response_model=schemas.NoticeOut)
def get_notice_by_id(
    notice_id: int,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    notice = crud.get_notice(db_session_basede26, notice_id)
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")
    return notice

@app.post("/api/notices", response_model=schemas.NoticeOut, status_code=201)
def create_notice(
    notice: schemas.NoticeCreate,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    return crud.create_notice(db_session_basede26, notice)

@app.put("/api/notices/{notice_id}", response_model=schemas.NoticeOut)
def update_notice(
    notice_id: int,
    notice: schemas.NoticeCreate,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    updated = crud.update_notice(db_session_basede26, notice_id, notice)
    if not updated:
        raise HTTPException(status_code=404, detail="Notice not found")
    return updated

@app.delete("/api/notices/{notice_id}", response_model=schemas.NoticeOut)
def delete_notice(
    notice_id: int,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    deleted = crud.delete_notice(db_session_basede26, notice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notice not found")
    return deleted

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8675)
