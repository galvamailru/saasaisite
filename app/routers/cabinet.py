"""Cabinet: только для зарегистрированных (JWT). Файлы, галереи, промпт, админ-чат."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth_service import decode_jwt, get_tenant_user_by_id
from app.services.cabinet_service import get_tenant_by_slug
from app.schemas import (
    DialogDetailResponse,
    DialogListResponse,
    DialogListItem,
    MessageInDialog,
    ProfileResponse,
    ProfileUpdate,
    SavedItemCreate,
    SavedItemResponse,
)
from app.services.cabinet_service import (
    get_dialog_messages,
    get_profile,
    get_saved_by_id,
    get_tenant_by_id,
    list_dialogs,
    list_saved,
    upsert_profile,
)
from app.models import SavedItem
from app.services.prompt_loader import load_prompt
from app.services.file_service import (
    list_user_files,
    get_user_file_by_id,
    create_user_file,
    set_file_trigger,
    delete_user_file,
    get_presigned_url,
)
from app.services.gallery_service import (
    list_galleries,
    get_gallery_by_id,
    create_gallery,
    delete_gallery,
    add_file_to_gallery,
    remove_from_gallery,
)
from app.schemas import (
    UserFileResponse,
    FileTriggerUpdate,
    GalleryResponse,
    GalleryItemResponse,
    GalleryCreate,
    GalleryAddItem,
    AdminChatRequest,
    AdminChatResponse,
    PromptUpdate,
)
from app.config import PROJECT_ROOT
from app.services.admin_chat_service import handle_admin_message

router = APIRouter(prefix="/api/v1/tenants", tags=["cabinet"])


@router.get("/by-slug/{slug}")
async def get_tenant_by_slug_endpoint(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    return {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name}


def get_cabinet_user_id(
    request: Request,
    authorization: str | None = Header(None),
) -> str:
    """Личный кабинет только для зарегистрированных. Требуется JWT."""
    tenant_id = request.path_params.get("tenant_id")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация. Войдите в личный кабинет.")
    token = authorization[7:].strip()
    payload = decode_jwt(token)
    if not payload or str(payload.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    return str(payload["sub"])


async def get_cabinet_user(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Личный кабинет только для зарегистрированных. Возвращает user_id после проверки TenantUser."""
    tenant_id = request.path_params.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация. Войдите в личный кабинет.")
    token = authorization[7:].strip()
    payload = decode_jwt(token)
    if not payload or str(payload.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    user_id = str(payload["sub"])
    user = await get_tenant_user_by_id(db, UUID(tenant_id), user_id)
    if not user or not user.email_confirmed_at:
        raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
    return user_id


# Dialogs (только для зарегистрированных)
@router.get("/{tenant_id:uuid}/me/dialogs", response_model=DialogListResponse)
async def list_user_dialogs(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    total, items = await list_dialogs(db, tenant_id, user_id, limit=limit, offset=offset)
    return DialogListResponse(
        total=total,
        items=[
            DialogListItem(
                id=d["dialog"].id,
                created_at=d["dialog"].created_at,
                updated_at=d["dialog"].updated_at,
                preview=d["preview"],
            )
            for d in items
        ],
    )


@router.get("/{tenant_id:uuid}/me/dialogs/{dialog_id:uuid}", response_model=DialogDetailResponse)
async def get_user_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    messages = await get_dialog_messages(db, tenant_id, user_id, dialog_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="dialog not found")
    return DialogDetailResponse(
        id=dialog_id,
        messages=[MessageInDialog(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )


# Saved
@router.get("/{tenant_id:uuid}/me/saved", response_model=list[SavedItemResponse])
async def list_user_saved(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    _, items = await list_saved(db, tenant_id, user_id, limit=limit, offset=offset)
    return [SavedItemResponse.model_validate(i) for i in items]


@router.post("/{tenant_id:uuid}/me/saved", response_model=SavedItemResponse, status_code=201)
async def create_saved(
    tenant_id: UUID,
    body: SavedItemCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    item = SavedItem(
        tenant_id=tenant_id,
        user_id=user_id,
        type=body.type,
        reference_id=body.reference_id,
    )
    db.add(item)
    await db.flush()
    return SavedItemResponse.model_validate(item)


@router.delete("/{tenant_id:uuid}/me/saved/{saved_id:uuid}", status_code=204)
async def delete_saved(
    tenant_id: UUID,
    saved_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    item = await get_saved_by_id(db, tenant_id, user_id, saved_id)
    if not item:
        raise HTTPException(status_code=404, detail="saved item not found")
    await db.delete(item)
    await db.flush()


# Profile
@router.get("/{tenant_id:uuid}/me/profile", response_model=ProfileResponse)
async def get_user_profile(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    profile = await get_profile(db, tenant_id, user_id)
    if not profile:
        return ProfileResponse(user_id=user_id, display_name=None, contact=None)
    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        contact=profile.contact,
    )


@router.patch("/{tenant_id:uuid}/me/profile", response_model=ProfileResponse)
async def update_user_profile(
    tenant_id: UUID,
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    profile = await upsert_profile(
        db, tenant_id, user_id,
        display_name=body.display_name,
        contact=body.contact,
    )
    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        contact=profile.contact,
    )


# Промпт чат-бота тенанта (просмотр и сохранение в БД — каждый админ настраивает своего бота)
@router.get("/{tenant_id:uuid}/me/prompt")
async def get_agent_prompt(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    if getattr(tenant, "system_prompt", None) and (tenant.system_prompt or "").strip():
        return {"prompt": tenant.system_prompt}
    try:
        text = load_prompt(PROJECT_ROOT)
        return {"prompt": text}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/{tenant_id:uuid}/me/prompt")
async def update_agent_prompt(
    tenant_id: UUID,
    body: PromptUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    tenant.system_prompt = body.prompt.strip() or None
    await db.flush()
    return {"prompt": tenant.system_prompt or ""}


# Файлы пользователя (MinIO)
@router.get("/{tenant_id:uuid}/me/files", response_model=list[UserFileResponse])
async def list_files(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    _, items = await list_user_files(db, tenant_id, user_id, limit=limit, offset=offset)
    return [
        UserFileResponse(
            id=uf.id,
            filename=uf.filename,
            content_type=uf.content_type,
            trigger=uf.trigger,
            created_at=uf.created_at,
            url=get_presigned_url(uf.minio_key),
        )
        for uf in items
    ]


@router.post("/{tenant_id:uuid}/me/files", response_model=UserFileResponse, status_code=201)
async def upload_file(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    file: UploadFile = File(...),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    uf = await create_user_file(
        db, tenant_id, user_id,
        file.filename or "file",
        file.content_type or "application/octet-stream",
        data,
    )
    return UserFileResponse(
        id=uf.id,
        filename=uf.filename,
        content_type=uf.content_type,
        trigger=uf.trigger,
        created_at=uf.created_at,
        url=get_presigned_url(uf.minio_key),
    )


@router.patch("/{tenant_id:uuid}/me/files/{file_id:uuid}", response_model=UserFileResponse)
async def update_file_trigger(
    tenant_id: UUID,
    file_id: UUID,
    body: FileTriggerUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    uf = await set_file_trigger(db, tenant_id, user_id, file_id, body.trigger)
    if not uf:
        raise HTTPException(status_code=404, detail="file not found")
    return UserFileResponse(
        id=uf.id,
        filename=uf.filename,
        content_type=uf.content_type,
        trigger=uf.trigger,
        created_at=uf.created_at,
        url=get_presigned_url(uf.minio_key),
    )


@router.get("/{tenant_id:uuid}/me/files/{file_id:uuid}/url")
async def get_file_url_endpoint(
    tenant_id: UUID,
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    expires: int = Query(3600, ge=60, le=86400),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    uf = await get_user_file_by_id(db, tenant_id, user_id, file_id)
    if not uf:
        raise HTTPException(status_code=404, detail="file not found")
    return {"url": get_presigned_url(uf.minio_key, expires)}


@router.delete("/{tenant_id:uuid}/me/files/{file_id:uuid}", status_code=204)
async def delete_file(
    tenant_id: UUID,
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await delete_user_file(db, tenant_id, user_id, file_id)
    if not ok:
        raise HTTPException(status_code=404, detail="file not found")


# Галереи
@router.get("/{tenant_id:uuid}/me/galleries", response_model=list[GalleryResponse])
async def list_galleries_route(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    galleries = await list_galleries(db, tenant_id, user_id)
    from sqlalchemy import select, func
    from app.models import GalleryItem
    result = []
    for g in galleries:
        count = await db.execute(select(func.count()).select_from(GalleryItem).where(GalleryItem.gallery_id == g.id))
        result.append(GalleryResponse(
            id=g.id,
            name=g.name,
            created_at=g.created_at,
            item_count=count.scalar() or 0,
        ))
    return result


@router.post("/{tenant_id:uuid}/me/galleries", response_model=GalleryResponse, status_code=201)
async def create_gallery_route(
    tenant_id: UUID,
    body: GalleryCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    g = await create_gallery(db, tenant_id, user_id, body.name)
    return GalleryResponse(id=g.id, name=g.name, created_at=g.created_at, item_count=0)


@router.delete("/{tenant_id:uuid}/me/galleries/{gallery_id:uuid}", status_code=204)
async def delete_gallery_route(
    tenant_id: UUID,
    gallery_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await delete_gallery(db, tenant_id, user_id, gallery_id)
    if not ok:
        raise HTTPException(status_code=404, detail="gallery not found")


@router.post("/{tenant_id:uuid}/me/galleries/{gallery_id:uuid}/items", response_model=GalleryItemResponse, status_code=201)
async def add_to_gallery_route(
    tenant_id: UUID,
    gallery_id: UUID,
    body: GalleryAddItem,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    item = await add_file_to_gallery(db, tenant_id, user_id, gallery_id, body.user_file_id)
    if not item:
        raise HTTPException(status_code=404, detail="gallery or file not found")
    uf = await get_user_file_by_id(db, tenant_id, user_id, body.user_file_id)
    return GalleryItemResponse(
        id=item.id,
        user_file_id=item.user_file_id,
        position=item.position,
        filename=uf.filename if uf else None,
        url=get_presigned_url(uf.minio_key) if uf else None,
    )


@router.delete("/{tenant_id:uuid}/me/galleries/{gallery_id:uuid}/items/{item_id:uuid}", status_code=204)
async def remove_item_from_gallery(
    tenant_id: UUID,
    gallery_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await remove_from_gallery(db, tenant_id, user_id, gallery_id, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="item or gallery not found")


# Админ-чат: диалог без команд; бот сам понимает намерения и выполняет действия
@router.post("/{tenant_id:uuid}/admin/chat", response_model=AdminChatResponse)
async def admin_chat(
    tenant_id: UUID,
    body: AdminChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    history = [{"role": m.role, "content": m.content} for m in body.history]
    reply = await handle_admin_message(
        db, tenant_id, user_id, body.message.strip(), history=history
    )
    return AdminChatResponse(reply=reply)
