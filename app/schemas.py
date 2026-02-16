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


# Cabinet: prompt chunks (max 500 chars per chunk)
class PromptChunkResponse(BaseModel):
    id: UUID
    position: int
    content: str

    class Config:
        from_attributes = True


class PromptChunkCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    position: int | None = None


class PromptChunkUpdate(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=500)
    position: int | None = None


# Cabinet: embed code for iframe
class EmbedCodeResponse(BaseModel):
    """URL чата для iframe и готовый HTML-код для вставки."""
    chat_url: str
    iframe_code: str


# Admin chat
class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=8192)


class AdminChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)


class AdminChatResponse(BaseModel):
    reply: str
