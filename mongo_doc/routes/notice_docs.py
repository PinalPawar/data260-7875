"""HW6 Part 1 - CRUD route handlers for /api/doc/notices (MongoDB).

Status codes:
  201 created, 200 ok, 204 deleted,
  400 bad id / empty update, 404 not found,
  422 validation error (Pydantic, raised automatically by FastAPI),
  503 MongoDB unreachable, 500 any other database error.
"""
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Response, status
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from ..db import get_notices_collection
from ..schemas import NoticeDocCreate, NoticeDocUpdate, NoticeDocOut

router = APIRouter(prefix="/api/doc/notices", tags=["HW6 MongoDB notices"])


def _now():
    return datetime.now(timezone.utc)


def _oid(notice_id: str) -> ObjectId:
    try:
        return ObjectId(notice_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400,
                            detail=f"'{notice_id}' is not a valid MongoDB id.")


def _serialize(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["id"] = str(doc["_id"])
    return out


def _db_error(exc: PyMongoError, action: str):
    if isinstance(exc, ServerSelectionTimeoutError):
        raise HTTPException(status_code=503,
                            detail="MongoDB is not reachable. Is the container running?")
    raise HTTPException(status_code=500, detail=f"Database error while {action}.")


@router.post("", response_model=NoticeDocOut, status_code=status.HTTP_201_CREATED)
def create_notice_doc(payload: NoticeDocCreate):
    doc = payload.model_dump()
    doc["createdAt"] = doc["updatedAt"] = _now()
    try:
        col = get_notices_collection()
        res = col.insert_one(doc)
        return _serialize(col.find_one({"_id": res.inserted_id}))
    except PyMongoError as exc:
        _db_error(exc, "creating the notice")


@router.get("", response_model=list[NoticeDocOut])
def list_notice_docs():
    try:
        docs = get_notices_collection().find().sort("createdAt", -1)
        return [_serialize(d) for d in docs]
    except PyMongoError as exc:
        _db_error(exc, "listing notices")


@router.get("/{notice_id}", response_model=NoticeDocOut)
def get_notice_doc(notice_id: str):
    oid = _oid(notice_id)
    try:
        doc = get_notices_collection().find_one({"_id": oid})
    except PyMongoError as exc:
        _db_error(exc, "fetching the notice")
    if doc is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    return _serialize(doc)


@router.put("/{notice_id}", response_model=NoticeDocOut)
def update_notice_doc(notice_id: str, payload: NoticeDocUpdate):
    oid = _oid(notice_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")
    updates["updatedAt"] = _now()
    try:
        doc = get_notices_collection().find_one_and_update(
            {"_id": oid}, {"$set": updates}, return_document=ReturnDocument.AFTER)
    except PyMongoError as exc:
        _db_error(exc, "updating the notice")
    if doc is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    return _serialize(doc)


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice_doc(notice_id: str):
    oid = _oid(notice_id)
    try:
        res = get_notices_collection().delete_one({"_id": oid})
    except PyMongoError as exc:
        _db_error(exc, "deleting the notice")
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notice not found.")
    return Response(status_code=204)
