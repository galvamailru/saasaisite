"""Регистрация, подтверждение по email, логин, JWT."""
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from uuid import UUID

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Tenant, TenantUser
from app.services.email_service import send_confirmation_email

CONFIRM_TOKEN_EXPIRE_HOURS = 24
BCRYPT_MAX_PASSWORD_BYTES = 72


def _password_bytes(password: str) -> bytes:
    """Bcrypt accepts at most 72 bytes; truncate to avoid error."""
    return password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    raw = _password_bytes(password)
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    raw = _password_bytes(plain)
    return bcrypt.checkpw(raw, hashed.encode("ascii"))


def create_jwt(user_id: str, tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None


async def register_new_user_with_tenant(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[TenantUser, Tenant]:
    """
    Регистрация «один тенант на пользователя»: создаёт новый тенант и пользователя в нём.
    Email должен быть уникален глобально (не занят ни в одном тенанте).
    """
    email_norm = email.lower().strip()
    existing = (
        await db.execute(select(TenantUser).where(TenantUser.email == email_norm))
    ).scalar_one_or_none()
    if existing:
        raise ValueError("email_already_registered")
    slug = "u" + uuid.uuid4().hex[:12]
    name = email_norm.split("@")[0] if "@" in email_norm else "Моё пространство"
    tenant = Tenant(slug=slug, name=name or "Моё пространство")
    db.add(tenant)
    await db.flush()
    user = await register_user(db, tenant.id, email, password, tenant.slug)
    return user, tenant


async def register_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    password: str,
    tenant_slug: str,
) -> TenantUser:
    existing = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.email == email.lower().strip(),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("email_already_registered")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=CONFIRM_TOKEN_EXPIRE_HOURS)
    user = TenantUser(
        tenant_id=tenant_id,
        email=email.lower().strip(),
        password_hash=hash_password(password),
        confirmation_token=token,
        confirmation_token_expires_at=expires,
    )
    db.add(user)
    await db.flush()
    await send_confirmation_email(user.email, tenant_slug, token)
    return user


async def confirm_email(db: AsyncSession, tenant_id: UUID, token: str) -> TenantUser | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.confirmation_token == token,
            TenantUser.confirmation_token_expires_at > now,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    user.email_confirmed_at = now
    user.confirmation_token = None
    user.confirmation_token_expires_at = None
    await db.flush()
    return user


async def login_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    password: str,
) -> TenantUser | None:
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.email == email.lower().strip(),
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.email_confirmed_at:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_tenant_user_by_id(db: AsyncSession, tenant_id: UUID, user_id: str) -> TenantUser | None:
    try:
        uid = UUID(user_id)
    except ValueError:
        return None
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.id == uid,
            TenantUser.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()
