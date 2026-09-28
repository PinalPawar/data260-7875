from pydantic import BaseModel, EmailStr, Field


class NoticeBase(BaseModel):
    product: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    email: str
    description: str
    category: str


class NoticeCreate(NoticeBase):
    pass


class NoticeOut(NoticeBase):
    id: int

    class Config:
        from_attributes = True


class RegisterPayload(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=6)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str
