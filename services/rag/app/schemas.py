from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    tenant_id: UUID
    name: str = Field(..., max_length=512)


class DocumentListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    source_file_name: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    content_md: str
    source_file_name: str | None
    created_at: datetime

    class Config:
        from_attributes = True
