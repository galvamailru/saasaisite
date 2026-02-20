"""Регистрация с подтверждением по email, логин, JWT."""
import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
)
from app.services.auth_service import (
    confirm_email,
    create_jwt,
    get_or_create_superadmin_user,
    login_user,
    register_new_user_with_tenant,
    register_user,
    request_password_reset,
    set_password_by_reset_token,
)
from app.services.cabinet_service import get_tenant_by_id, get_tenant_by_slug
from app.services.email_service import send_password_reset_email

router = APIRouter(prefix="/api/v1/tenants", tags=["auth"])


@router.post("/register", response_model=RegisterResponse)
async def register_standalone(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Регистрация «один тенант на пользователя»: создаётся новый тенант и пользователь в нём.
    После подтверждения email вход по ссылке /{tenant_slug}/login.
    """
    try:
        user, tenant = await register_new_user_with_tenant(db, body.email, body.password)
    except ValueError as e:
        if str(e) == "email_already_registered":
            raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
        raise HTTPException(status_code=400, detail=str(e))
    return RegisterResponse(
        user_id=str(user.id),
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
    )


@router.post("/{tenant_id:uuid}/register", response_model=RegisterResponse)
async def register(
    tenant_id: UUID,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    tenant_slug = tenant.slug
    try:
        user = await register_user(db, tenant_id, body.email, body.password, tenant_slug)
    except ValueError as e:
        if str(e) == "email_already_registered":
            raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
        raise HTTPException(status_code=400, detail=str(e))
    return RegisterResponse(user_id=str(user.id))


@router.get("/{tenant_id:uuid}/confirm")
async def confirm(
    tenant_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    user = await confirm_email(db, tenant_id, token)
    if not user:
        raise HTTPException(status_code=400, detail="Неверная или просроченная ссылка подтверждения")
    return {"message": "Email подтверждён. Теперь вы можете войти."}


@router.get("/by-slug/{slug}/confirm")
async def confirm_by_slug(
    slug: str,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    user = await confirm_email(db, tenant.id, token)
    if not user:
        raise HTTPException(status_code=400, detail="Неверная или просроченная ссылка подтверждения")
    return {"message": "Email подтверждён. Теперь вы можете войти."}


@router.post("/{tenant_id:uuid}/login", response_model=LoginResponse)
async def login(
    tenant_id: UUID,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    if (tenant.settings or {}).get("blocked"):
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    # Вход суперадминистратора по учётке из .env (только для тенанта-администратора)
    if (
        app_settings.admin_tenant_slug
        and tenant.slug == app_settings.admin_tenant_slug
        and app_settings.superadmin_login
        and body.email.strip().lower() == app_settings.superadmin_login.strip().lower()
    ):
        expected = app_settings.superadmin_password
        if expected and hmac.compare_digest(body.password.encode("utf-8"), expected.encode("utf-8")):
            user = await get_or_create_superadmin_user(
                db, tenant_id, app_settings.superadmin_login.strip().lower(), expected
            )
            token = create_jwt(str(user.id), str(tenant_id))
            return LoginResponse(
                access_token=token,
                user_id=str(user.id),
                tenant_id=str(tenant_id),
            )
    user = await login_user(db, tenant_id, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль, либо email не подтверждён")
    token = create_jwt(str(user.id), str(tenant_id))
    return LoginResponse(
        access_token=token,
        user_id=str(user.id),
        tenant_id=str(tenant_id),
    )


@router.post("/by-slug/{slug}/forgot-password")
async def forgot_password(
    slug: str,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Запрос восстановления пароля: отправка письма со ссылкой на сброс (если пользователь с таким email есть и подтверждён)."""
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    user = await request_password_reset(db, tenant.id, body.email)
    if user:
        await send_password_reset_email(user.email, tenant.slug, user.reset_password_token)
    return {"message": "Если аккаунт с таким email зарегистрирован и подтверждён, на почту отправлена ссылка для сброса пароля."}


@router.post("/by-slug/{slug}/reset-password")
async def reset_password(
    slug: str,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Установка нового пароля по токену из письма."""
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    user = await set_password_by_reset_token(db, tenant.id, body.token, body.new_password)
    if not user:
        raise HTTPException(status_code=400, detail="Неверная или просроченная ссылка сброса пароля")
    return {"message": "Пароль изменён. Войдите с новым паролем."}
