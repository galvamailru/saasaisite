"""SQLAlchemy models: tenant, dialog, message, saved_item, user_profile."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    dialogs = relationship("Dialog", back_populates="tenant")
    messages = relationship("Message", back_populates="tenant")
    saved_items = relationship("SavedItem", back_populates="tenant")
    user_profiles = relationship("UserProfile", back_populates="tenant")
    tenant_users = relationship("TenantUser", back_populates="tenant")
    user_files = relationship("UserFile", back_populates="tenant")
    galleries = relationship("Gallery", back_populates="tenant")


class TenantUser(Base):
    """Зарегистрированный пользователь тенанта (email + пароль, подтверждение по почте). По умолчанию роль admin."""
    __tablename__ = "tenant_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmation_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="tenant_users")

    __table_args__ = (
        Index("ix_tenant_user_tenant_email", "tenant_id", "email", unique=True),
    )


class Dialog(Base):
    __tablename__ = "dialog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="dialogs")
    messages = relationship("Message", back_populates="dialog", order_by="Message.created_at")

    __table_args__ = (
        Index("ix_dialog_tenant_user_updated", "tenant_id", "user_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dialog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dialog.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="messages")
    dialog = relationship("Dialog", back_populates="messages")

    __table_args__ = (
        Index("ix_message_tenant_user", "tenant_id", "user_id"),
    )


class SavedItem(Base):
    __tablename__ = "saved_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="saved_items")

    __table_args__ = (
        Index("ix_saved_item_tenant_user", "tenant_id", "user_id"),
    )


class UserProfile(Base):
    __tablename__ = "user_profile"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="user_profiles")


class UserFile(Base):
    """Файл пользователя (админа) в MinIO. К файлу можно привязать триггер для промпта."""
    __tablename__ = "user_file"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)  # TenantUser.id
    minio_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="user_files")
    gallery_items = relationship("GalleryItem", back_populates="user_file")

    __table_args__ = (
        Index("ix_user_file_tenant_user", "tenant_id", "user_id"),
    )


class Gallery(Base):
    """Галерея изображений пользователя (админа)."""
    __tablename__ = "gallery"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="galleries")
    items = relationship("GalleryItem", back_populates="gallery", order_by="GalleryItem.position")

    __table_args__ = (
        Index("ix_gallery_tenant_user", "tenant_id", "user_id"),
    )


class GalleryItem(Base):
    """Элемент галереи — ссылка на UserFile."""
    __tablename__ = "gallery_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gallery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gallery.id", ondelete="CASCADE"), nullable=False
    )
    user_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_file.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    gallery = relationship("Gallery", back_populates="items")
    user_file = relationship("UserFile", back_populates="gallery_items")
