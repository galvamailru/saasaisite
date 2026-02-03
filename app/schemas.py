"""Pydantic schemas for API."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# Auth
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    message: str = "Письмо с подтверждением отправлено на указанный email."
    user_id: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str


# Chat (tenant_id from path)
class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1)
    dialog_id: UUID | None = None


# Cabinet: dialogs
class DialogListItem(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    preview: str | None = None

    class Config:
        from_attributes = True


class DialogListResponse(BaseModel):
    total: int
    items: list[DialogListItem]


class MessageInDialog(BaseModel):
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class DialogDetailResponse(BaseModel):
    id: UUID
    messages: list[MessageInDialog]


# Cabinet: saved
class SavedItemCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=32)
    reference_id: str = Field(..., min_length=1, max_length=256)


class SavedItemResponse(BaseModel):
    id: UUID
    type: str
    reference_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# Cabinet: profile
class ProfileResponse(BaseModel):
    user_id: str
    display_name: str | None = None
    contact: str | None = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=256)
    contact: str | None = Field(None, max_length=256)


# Cabinet: files (MinIO)
class UserFileResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    trigger: str | None = None
    created_at: datetime
    url: str | None = None

    class Config:
        from_attributes = True


class FileTriggerUpdate(BaseModel):
    trigger: str | None = Field(None, max_length=128)


# Cabinet: galleries
class GalleryResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    item_count: int = 0

    class Config:
        from_attributes = True


class GalleryItemResponse(BaseModel):
    id: UUID
    user_file_id: UUID
    position: int
    filename: str | None = None
    url: str | None = None

    class Config:
        from_attributes = True


class GalleryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)


class GalleryAddItem(BaseModel):
    user_file_id: UUID


# Admin chat (slash-commands)
class AdminChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)


class AdminChatResponse(BaseModel):
    reply: str
