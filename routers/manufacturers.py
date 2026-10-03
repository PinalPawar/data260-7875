"""
HW5 Part 1: CRUD for the related entity (Manufacturer) plus the
relationship query GET /api/manufacturers/{id}/notices.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

import crud
import schemas
from database import get_db_session_basede26
from models import User
from routers.session_auth import require_session

router = APIRouter(prefix="/api/manufacturers", tags=["manufacturers"])


@router.post("", response_model=schemas.ManufacturerOut, status_code=201)
def create_manufacturer(
    payload: schemas.ManufacturerCreate,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    try:
        return crud.create_manufacturer(db_session_basede26, payload)
    except crud.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=schemas.ManufacturerPage)
def list_manufacturers(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    items, total = crud.list_manufacturers(db_session_basede26, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{manufacturer_id}", response_model=schemas.ManufacturerOut)
def get_manufacturer(
    manufacturer_id: int,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    try:
        return crud.get_manufacturer(db_session_basede26, manufacturer_id)
    except crud.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{manufacturer_id}", response_model=schemas.ManufacturerOut)
def update_manufacturer(
    manufacturer_id: int,
    payload: schemas.ManufacturerCreate,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    try:
        return crud.update_manufacturer(db_session_basede26, manufacturer_id, payload)
    except crud.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except crud.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/{manufacturer_id}", status_code=204)
def delete_manufacturer(
    manufacturer_id: int,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    try:
        crud.delete_manufacturer(db_session_basede26, manufacturer_id)
    except crud.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except crud.Conflict as exc:
        # Deliberately NOT cascading: a manufacturer with notices can't be deleted.
        raise HTTPException(status_code=409, detail=str(exc))
    return Response(status_code=204)


@router.get("/{manufacturer_id}/notices", response_model=List[schemas.NoticeOut])
def notices_for_manufacturer(
    manufacturer_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    """Relationship query: every notice issued by one manufacturer."""
    try:
        return crud.list_notices_for_manufacturer(db_session_basede26, manufacturer_id, skip, limit)
    except crud.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
