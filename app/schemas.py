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
    tenant_id: str | None = None  # при регистрации «один тенант на пользователя»
    tenant_slug: str | None = None  # ссылка на вход: /{tenant_slug}/login


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
    is_test: bool = False  # режим теста в админке — не сохранять диалоги/сообщения в БД


# Cabinet: dialogs
class DialogListItem(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    preview: str | None = None
    user_id: str | None = None
    message_count: int = 0
    has_lead: bool = False

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


# Cabinet: profile + анкета для коммерческого промпта
class PromptSurvey(BaseModel):
    # Блок 1. Роль и глобальная цель
    company_and_agent_name: str | None = None
    main_problem: str | None = None
    main_goal: str | None = None
    tone_of_voice: str | None = None

    # Блок 2. Воронка диалога и первый контакт
    greeting: str | None = None
    generic_question_answer: str | None = None
    return_to_dialog_phrase: str | None = None

    # Блок 3. Продукты / триггеры (упрощённо, в текстовом виде)
    product1: str | None = None
    product1_triggers: str | None = None
    product1_reaction: str | None = None
    product1_qualifying_question: str | None = None

    product2: str | None = None
    product2_triggers: str | None = None
    product2_reaction: str | None = None
    product2_qualifying_question: str | None = None

    product3: str | None = None
    product3_triggers: str | None = None
    product3_reaction: str | None = None
    product3_qualifying_question: str | None = None

    # Блок 4. Квалификация и переход к действию
    hot_lead_markers: str | None = None
    transition_phrases: str | None = None
    contacts_to_collect: str | None = None
    phone_format_notes: str | None = None

    # Блок 5. Нештатные ситуации
    abuse_reaction: str | None = None
    unknown_answer_reaction: str | None = None


class ProfileResponse(BaseModel):
    user_id: str
    display_name: str | None = None
    contact: str | None = None
    # Системный промпт пользовательского бота для этого тенанта (основной, поверх него идут чанки).
    system_prompt: str | None = None
    # Ответы на анкету для построения коммерческого промпта.
    prompt_survey: PromptSurvey | None = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=256)
    contact: str | None = Field(None, max_length=256)
    system_prompt: str | None = Field(None, max_length=20000)
    prompt_survey: PromptSurvey | None = None


# Cabinet: prompt chunks (max 2000 chars content; optional question from admin bot)
class PromptChunkResponse(BaseModel):
    id: UUID
    position: int
    question: str | None = None
    content: str

    class Config:
        from_attributes = True


class PromptChunkCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    question: str | None = Field(None, max_length=1000)
    position: int | None = None


class PromptChunkUpdate(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=2000)
    question: str | None = Field(None, max_length=1000)
    position: int | None = None


# Cabinet: admin bot prompt (system + chunks: question + detailed description)
class AdminPromptResponse(BaseModel):
    """Текущий системный промпт админ-бота."""
    system_prompt: str | None = None


class AdminPromptUpdate(BaseModel):
    """Обновление системного промпта админ-бота."""
    system_prompt: str | None = None


class AdminPromptChunkResponse(BaseModel):
    id: UUID
    position: int
    question: str | None = None
    content: str

    class Config:
        from_attributes = True


class AdminPromptChunkCreate(BaseModel):
    content: str = Field(..., min_length=1)
    question: str | None = Field(None, max_length=1000)
    position: int | None = None


class AdminPromptChunkUpdate(BaseModel):
    content: str | None = None
    question: str | None = Field(None, max_length=1000)
    position: int | None = None


# Cabinet: leads (contacts from dialogs)
class LeadResponse(BaseModel):
    id: UUID
    user_id: str
    dialog_id: UUID
    contact_text: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
