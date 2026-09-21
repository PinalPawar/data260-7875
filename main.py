import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

from routers.auth import router as auth_router

app = FastAPI(title="Grocery Recall Notices API")

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

# Auth routes (/, /login, /logout, /dashboard) live in their own router.
app.include_router(auth_router)

class Notice(BaseModel):
    id: int
    product: str
    manufacturer: str
    email: str
    description: str
    category: str

class NoticeCreate(BaseModel):
    product: str
    manufacturer: str
    email: str
    description: str
    category: str

notices: List[Notice] = [
    Notice(
        id=1,
        product="Peanut Butter",
        manufacturer="ACME Foods",
        email="info@acmefoods.com",
        description="Salmonella contamination detected in select jars.",
        category="bacterialContamination",
    )
]

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

@app.get("/api/notices", response_model=List[Notice])
def get_notices(q: Optional[str] = None):
    if q:
        q_lower = q.lower()
        return [
            n for n in notices
            if q_lower in n.product.lower() or q_lower in n.manufacturer.lower()
        ]
    return notices

@app.post("/api/notices", response_model=Notice, status_code=201)
def create_notice(notice: NoticeCreate):
    new_id = max([n.id for n in notices], default=0) + 1
    new_notice = Notice(id=new_id, **notice.dict())
    notices.append(new_notice)
    return new_notice

@app.put("/api/notices/{notice_id}", response_model=Notice)
def update_notice(notice_id: int, notice: NoticeCreate):
    for i, n in enumerate(notices):
        if n.id == notice_id:
            updated = Notice(id=notice_id, **notice.dict())
            notices[i] = updated
            return updated
    raise HTTPException(status_code=404, detail="Notice not found")

@app.delete("/api/notices/highest")
def delete_highest_notice():
    if not notices:
        raise HTTPException(status_code=404, detail="No notices to delete")
    highest = max(notices, key=lambda n: n.id)
    notices.remove(highest)
    return {"deleted_id": highest.id}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8675)
