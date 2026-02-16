"""Cabinet: только для зарегистрированных (JWT). Диалоги, чанки промпта, вставка на сайт, админ-чат, профиль."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth_service import decode_jwt, get_tenant_user_by_id
from app.services.cabinet_service import get_tenant_by_slug
from app.schemas import (
    DialogDetailResponse,
    DialogListResponse,
    DialogListItem,
    LeadResponse,
    MessageInDialog,
    ProfileResponse,
    ProfileUpdate,
    SavedItemCreate,
    SavedItemResponse,
    PromptChunkResponse,
    PromptChunkCreate,
    PromptChunkUpdate,
    EmbedCodeResponse,
    AdminChatRequest,
    AdminChatResponse,
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
from app.services.prompt_chunk_service import (
    list_chunks,
    create_chunk,
    update_chunk,
    delete_chunk,
)
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
    tenant_id_raw = request.path_params.get("tenant_id")
    if not tenant_id_raw:
        raise HTTPException(status_code=400, detail="tenant_id required")
    tenant_id = tenant_id_raw if isinstance(tenant_id_raw, UUID) else UUID(str(tenant_id_raw))
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация. Войдите в личный кабинет.")
    token = authorization[7:].strip()
    payload = decode_jwt(token)
    if not payload or str(payload.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    user_id = str(payload["sub"])
    user = await get_tenant_user_by_id(db, tenant_id, user_id)
    if not user or not user.email_confirmed_at:
        raise HTTPException(status_code=403, detail="Доступ только для зарегистрированных пользователей")
    return user_id


# Dialogs
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


# Prompt chunks (max 500 chars each)
@router.get("/{tenant_id:uuid}/me/prompt/chunks", response_model=list[PromptChunkResponse])
async def list_prompt_chunks(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chunks = await list_chunks(db, tenant_id)
    return [PromptChunkResponse(id=c.id, position=c.position, content=c.content) for c in chunks]


@router.post("/{tenant_id:uuid}/me/prompt/chunks", response_model=PromptChunkResponse, status_code=201)
async def create_prompt_chunk(
    tenant_id: UUID,
    body: PromptChunkCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    try:
        chunk = await create_chunk(db, tenant_id, body.content, body.position)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PromptChunkResponse(id=chunk.id, position=chunk.position, content=chunk.content)


@router.patch("/{tenant_id:uuid}/me/prompt/chunks/{chunk_id:uuid}", response_model=PromptChunkResponse)
async def patch_prompt_chunk(
    tenant_id: UUID,
    chunk_id: UUID,
    body: PromptChunkUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chunk = await update_chunk(db, tenant_id, chunk_id, content=body.content, position=body.position)
    if not chunk:
        raise HTTPException(status_code=404, detail="chunk not found")
    return PromptChunkResponse(id=chunk.id, position=chunk.position, content=chunk.content)


@router.delete("/{tenant_id:uuid}/me/prompt/chunks/{chunk_id:uuid}", status_code=204)
async def delete_prompt_chunk(
    tenant_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await delete_chunk(db, tenant_id, chunk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="chunk not found")


# Лиды (контакты из диалогов)
@router.get("/{tenant_id:uuid}/me/leads", response_model=list[LeadResponse])
async def list_user_leads(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    _, items = await list_leads(db, tenant_id, limit=limit, offset=offset)
    return [LeadResponse.model_validate(l) for l in items]


# Embed: код iframe для вставки чата на сайт
@router.get("/{tenant_id:uuid}/me/embed", response_model=EmbedCodeResponse)
async def get_embed_code(
    tenant_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    base_url = str(request.base_url).rstrip("/")
    chat_url = f"{base_url}/{tenant.slug}/chat/embed"
    iframe_code = f'<iframe src="{chat_url}" width="400" height="600" frameborder="0" title="Чат"></iframe>'
    return EmbedCodeResponse(chat_url=chat_url, iframe_code=iframe_code)


# Admin chat
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
