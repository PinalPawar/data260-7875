"""HW6 Part 1 - Pydantic data models for a recall-notice document.

Field mapping to the assignment's generic requirements:
  required short text (max 100)  -> product
  optional description           -> description
  status-style enum with default -> status (default "announced")
  category-style fixed options   -> category (the 4 DOMAIN_SCHEMA.md values)
  required date/time             -> recall_date
  automatic timestamps           -> createdAt / updatedAt (set by the server)
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

STATUS_VALUES = ["announced", "ongoing", "resolved"]
CATEGORY_VALUES = ["supplyShortage", "bacterialContamination",
                   "foreignMaterial", "mislabelling"]

StatusEnum = Literal["announced", "ongoing", "resolved"]
CategoryEnum = Literal["supplyShortage", "bacterialContamination",
                       "foreignMaterial", "mislabelling"]


class NoticeDocCreate(BaseModel):
    # extra="forbid": unknown fields are rejected instead of silently stored
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    status: StatusEnum = "announced"
    category: CategoryEnum
    recall_date: datetime


class NoticeDocUpdate(BaseModel):
    """Every field optional - PUT only changes the fields that are sent."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[StatusEnum] = None
    category: Optional[CategoryEnum] = None
    recall_date: Optional[datetime] = None


class ChatRequest(BaseModel):
    """HW6 Part 2 - body of POST /api/chat. session_id is optional: when it
    is left out the server starts a new session and returns its id."""
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(..., min_length=1, max_length=64)
    session_id: Optional[str] = Field(None, min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)


class NoticeDocOut(BaseModel):
    id: str
    product: str
    description: Optional[str] = None
    status: StatusEnum
    category: CategoryEnum
    recall_date: datetime
    createdAt: datetime
    updatedAt: datetime
