from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Unique-field formats (HW5 Part 1: "Ensure the unique field's format is validated").
MANUFACTURER_CODE_PATTERN = r"^MFR-\d{4}$"        # e.g. MFR-0001
NOTICE_CODE_PATTERN = r"^RCL-\d{4}-\d{5}$"         # e.g. RCL-2026-00001

Category = Literal["supplyShortage", "bacterialContamination", "foreignMaterial", "mislabelling"]


# --- Manufacturer (related entity) -----------------------------------------
class ManufacturerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    headquarters: str = Field(min_length=1, max_length=255)
    code: str = Field(pattern=MANUFACTURER_CODE_PATTERN, description="Format MFR-0001")


class ManufacturerCreate(ManufacturerBase):
    pass


class ManufacturerOut(ManufacturerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ManufacturerPage(BaseModel):
    items: List[ManufacturerOut]
    total: int
    page: int
    page_size: int


# --- Notice (primary domain entity) ----------------------------------------
class NoticeBase(BaseModel):
    product: str = Field(min_length=1, max_length=255)
    notice_code: str = Field(pattern=NOTICE_CODE_PATTERN, description="Format RCL-2026-00001")
    units_affected: int = Field(default=0, ge=0)
    manufacturer_id: int = Field(gt=0)
    email: EmailStr
    description: str = Field(min_length=1)
    category: Category


class NoticeCreate(NoticeBase):
    pass


class NoticeOut(NoticeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str  # already-stored rows are returned as-is
    category: str
    manufacturer_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# --- Auth (HW4) -------------------------------------------------------------
class RegisterPayload(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=6)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str
