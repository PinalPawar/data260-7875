from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(title="Grocery Recall Notices API")

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

@app.get("/")
def home():
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
