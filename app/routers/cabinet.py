"""Cabinet: только для зарегистрированных (JWT). Диалоги, чанки промпта, вставка на сайт, админ-чат, галерея, RAG, профиль."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
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
    AdminPromptResponse,
    AdminPromptUpdate,
    AdminPromptChunkResponse,
    AdminPromptChunkCreate,
    AdminPromptChunkUpdate,
    EmbedCodeResponse,
    AdminChatRequest,
    AdminChatResponse,
)
from app.services.cabinet_service import (
    get_dialog_messages,
    get_dialog_messages_for_tenant,
    get_profile,
    get_saved_by_id,
    get_tenant_by_id,
    list_dialogs,
    list_leads,
    list_saved,
    list_tenant_dialogs,
    upsert_profile,
)
from app.models import SavedItem
from app.services.prompt_chunk_service import (
    list_chunks,
    create_chunk,
    update_chunk,
    delete_chunk,
)
from app.services.admin_prompt_service import (
    get_admin_system_prompt,
    set_admin_system_prompt,
    list_admin_chunks,
    create_admin_chunk,
    update_admin_chunk,
    delete_admin_chunk,
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


# Dialogs (все диалоги тенанта — посетители iframe; админ видит все)
@router.get("/{tenant_id:uuid}/me/tenant/dialogs", response_model=DialogListResponse)
async def list_tenant_dialogs_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
):
    from datetime import datetime as dt
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    d_from = dt.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    d_to = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    total, items = await list_tenant_dialogs(
        db, tenant_id, limit=limit, offset=offset, date_from=d_from, date_to=d_to
    )
    return DialogListResponse(
        total=total,
        items=[
            DialogListItem(
                id=d["dialog"].id,
                created_at=d["dialog"].created_at,
                updated_at=d["dialog"].updated_at,
                preview=d["preview"],
                user_id=d["dialog"].user_id,
                message_count=d.get("message_count", 0),
                has_lead=d.get("has_lead", False),
            )
            for d in items
        ],
    )


@router.get("/{tenant_id:uuid}/me/tenant/dialogs/{dialog_id:uuid}", response_model=DialogDetailResponse)
async def get_tenant_dialog(
    tenant_id: UUID,
    dialog_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    messages = await get_dialog_messages_for_tenant(db, tenant_id, dialog_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="dialog not found")
    return DialogDetailResponse(
        id=dialog_id,
        messages=[MessageInDialog(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )


# Dialogs (только свои — оставлено для совместимости, в UI используем tenant/dialogs)
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
    system_prompt = tenant.system_prompt if getattr(tenant, "system_prompt", None) else None
    if not profile:
        return ProfileResponse(
            user_id=user_id,
            display_name=None,
            contact=None,
            system_prompt=system_prompt,
            prompt_survey=None,
        )
    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        contact=profile.contact,
        system_prompt=system_prompt,
        prompt_survey=profile.prompt_survey or None,
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
        prompt_survey=body.prompt_survey.model_dump() if body.prompt_survey is not None else None,
    )
    # Обновление системного промпта пользовательского бота для этого тенанта
    if body.system_prompt is not None:
        tenant.system_prompt = (body.system_prompt or "").strip() or None
        await db.flush()
    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        contact=profile.contact,
        system_prompt=tenant.system_prompt,
        prompt_survey=profile.prompt_survey or None,
    )


# Prompt chunks (max 2000 chars each)
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
    return [PromptChunkResponse(id=c.id, position=c.position, question=c.question, content=c.content) for c in chunks]


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
        chunk = await create_chunk(db, tenant_id, body.content, body.position, body.question)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PromptChunkResponse(id=chunk.id, position=chunk.position, question=chunk.question, content=chunk.content)


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
    chunk = await update_chunk(
        db, tenant_id, chunk_id, content=body.content, position=body.position, question=body.question
    )
    if not chunk:
        raise HTTPException(status_code=404, detail="chunk not found")
    return PromptChunkResponse(id=chunk.id, position=chunk.position, question=chunk.question, content=chunk.content)


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


# Admin bot prompt (system + chunks: question + detailed description)
@router.get("/{tenant_id:uuid}/me/admin-prompt", response_model=AdminPromptResponse)
async def get_admin_prompt(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    system_prompt = await get_admin_system_prompt(db, tenant_id)
    return AdminPromptResponse(system_prompt=system_prompt)


@router.patch("/{tenant_id:uuid}/me/admin-prompt", response_model=AdminPromptResponse)
async def patch_admin_prompt(
    tenant_id: UUID,
    body: AdminPromptUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    await set_admin_system_prompt(db, tenant_id, body.system_prompt)
    system_prompt = await get_admin_system_prompt(db, tenant_id)
    return AdminPromptResponse(system_prompt=system_prompt)


@router.get("/{tenant_id:uuid}/me/admin-prompt/chunks", response_model=list[AdminPromptChunkResponse])
async def list_admin_prompt_chunks(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chunks = await list_admin_chunks(db, tenant_id)
    return [
        AdminPromptChunkResponse(id=c.id, position=c.position, question=c.question, content=c.content)
        for c in chunks
    ]


@router.post(
    "/{tenant_id:uuid}/me/admin-prompt/chunks",
    response_model=AdminPromptChunkResponse,
    status_code=201,
)
async def create_admin_prompt_chunk(
    tenant_id: UUID,
    body: AdminPromptChunkCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    try:
        chunk = await create_admin_chunk(
            db, tenant_id, body.content, body.position, body.question
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AdminPromptChunkResponse(
        id=chunk.id, position=chunk.position, question=chunk.question, content=chunk.content
    )


@router.patch(
    "/{tenant_id:uuid}/me/admin-prompt/chunks/{chunk_id:uuid}",
    response_model=AdminPromptChunkResponse,
)
async def patch_admin_prompt_chunk(
    tenant_id: UUID,
    chunk_id: UUID,
    body: AdminPromptChunkUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chunk = await update_admin_chunk(
        db, tenant_id, chunk_id,
        content=body.content,
        position=body.position,
        question=body.question,
    )
    if not chunk:
        raise HTTPException(status_code=404, detail="chunk not found")
    return AdminPromptChunkResponse(
        id=chunk.id, position=chunk.position, question=chunk.question, content=chunk.content
    )


@router.delete(
    "/{tenant_id:uuid}/me/admin-prompt/chunks/{chunk_id:uuid}",
    status_code=204,
)
async def delete_admin_prompt_chunk(
    tenant_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    ok = await delete_admin_chunk(db, tenant_id, chunk_id)
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
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
):
    from datetime import datetime as dt
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    d_from = dt.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    d_to = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    _, items = await list_leads(
        db, tenant_id, limit=limit, offset=offset, date_from=d_from, date_to=d_to
    )
    return [LeadResponse.model_validate(l) for l in items]


# Embed: код iframe для вставки чата на сайт (URL из FRONTEND_BASE_URL, в пути — slug тенанта)
@router.get("/{tenant_id:uuid}/me/embed", response_model=EmbedCodeResponse)
async def get_embed_code(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_cabinet_user),
):
    from app.config import settings
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    base_url = (settings.frontend_base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "https://YOUR_DOMAIN"
    chat_url = f"{base_url}/{tenant.slug}/chat/embed"
    iframe_code = (
        f'<iframe src="{chat_url}" '
        f'data-tenant-id="{tenant.id}" data-tenant-slug="{tenant.slug}" '
        f'width="400" height="600" frameborder="0" title="Чат"></iframe>'
    )
    return EmbedCodeResponse(chat_url=chat_url, iframe_code=iframe_code)


# --- Прокси к микросервисам: Галерея и RAG (редактирование через UI кабинета) ---
from app.services.microservices_client import gallery_get_file, gallery_request, rag_request


@router.get("/{tenant_id:uuid}/me/gallery/groups")
async def gallery_list_groups(
    tenant_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("GET", f"/api/v1/groups?tenant_id={tenant_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.get("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_get_group(
    tenant_id: UUID,
    group_id: UUID,
    request: Request,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("GET", f"/api/v1/groups/{group_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    data = json.loads(text)
    base = str(request.base_url).rstrip("/")
    for img in data.get("images") or []:
        img["url"] = f"{base}/api/v1/tenants/{tenant_id}/me/gallery/groups/{group_id}/images/{img['id']}/file"
    return JSONResponse(content=data)


@router.post("/{tenant_id:uuid}/me/gallery/groups")
async def gallery_create_group(
    tenant_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
):
    body["tenant_id"] = str(tenant_id)
    status, text = await gallery_request("POST", "/api/v1/groups", tenant_id, json_body=body)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.patch("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_update_group(
    tenant_id: UUID,
    group_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("PATCH", f"/api/v1/groups/{group_id}", tenant_id, json_body=body)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.delete("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}")
async def gallery_delete_group(
    tenant_id: UUID,
    group_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("DELETE", f"/api/v1/groups/{group_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


@router.post("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images")
async def gallery_add_image(
    tenant_id: UUID,
    group_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_cabinet_user),
):
    content = await file.read()
    files = {"file": (file.filename or "image", content, file.content_type or "application/octet-stream")}
    status, text = await gallery_request(
        "POST", f"/api/v1/groups/{group_id}/images", tenant_id, files=files
    )
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    data = json.loads(text)
    base = str(request.base_url).rstrip("/")
    data["url"] = f"{base}/api/v1/tenants/{tenant_id}/me/gallery/groups/{group_id}/images/{data['id']}/file"
    return JSONResponse(content=data, status_code=201)


@router.get("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images/{image_id:uuid}/file")
async def gallery_serve_image(
    tenant_id: UUID,
    group_id: UUID,
    image_id: UUID,
):
    """Отдаёт бинарный файл изображения из БД галереи. Без авторизации — URL с uuid непредсказуем."""
    status, content, content_type = await gallery_get_file(
        f"/api/v1/groups/{group_id}/images/{image_id}/file"
    )
    if status != 200:
        return Response(status_code=status)
    return Response(content=content, media_type=content_type or "application/octet-stream")


@router.delete("/{tenant_id:uuid}/me/gallery/groups/{group_id:uuid}/images/{image_id:uuid}")
async def gallery_delete_image(
    tenant_id: UUID,
    group_id: UUID,
    image_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await gallery_request("DELETE", f"/api/v1/groups/{group_id}/images/{image_id}", tenant_id)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


@router.get("/{tenant_id:uuid}/me/rag/documents")
async def rag_list_documents(
    tenant_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("GET", f"/api/v1/documents", params={"tenant_id": str(tenant_id)})
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.get("/{tenant_id:uuid}/me/rag/documents/{document_id:uuid}")
async def rag_get_document(
    tenant_id: UUID,
    document_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("GET", f"/api/v1/documents/{document_id}")
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.post("/{tenant_id:uuid}/me/rag/documents/preview")
async def rag_preview_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    user_id: str = Depends(get_cabinet_user),
):
    """Преобразует PDF в markdown, возвращает текст без сохранения (для предпросмотра)."""
    content = await file.read()
    files = {"file": (file.filename or "doc.pdf", content, file.content_type or "application/pdf")}
    status, text = await rag_request("POST", "/api/v1/documents/preview", files=files)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text))


@router.post("/{tenant_id:uuid}/me/rag/documents/save")
async def rag_save_document(
    tenant_id: UUID,
    body: dict,
    user_id: str = Depends(get_cabinet_user),
):
    """Сохраняет документ в RAG из markdown (после предпросмотра)."""
    status, text = await rag_request(
        "POST",
        "/api/v1/documents/save",
        params={"tenant_id": str(tenant_id)},
        data=body,
    )
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.post("/{tenant_id:uuid}/me/rag/documents")
async def rag_upload_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    name: str = Form(""),
    user_id: str = Depends(get_cabinet_user),
):
    doc_name = (name or (file.filename or "document").replace(".pdf", "")).strip() or "document"
    params = {"tenant_id": str(tenant_id), "name": doc_name}
    content = await file.read()
    files = {"file": (file.filename or "doc.pdf", content, file.content_type or "application/pdf")}
    status, text = await rag_request("POST", "/api/v1/documents", params=params, files=files)
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return JSONResponse(content=json.loads(text), status_code=201)


@router.delete("/{tenant_id:uuid}/me/rag/documents/{document_id:uuid}")
async def rag_delete_document(
    tenant_id: UUID,
    document_id: UUID,
    user_id: str = Depends(get_cabinet_user),
):
    status, text = await rag_request("DELETE", f"/api/v1/documents/{document_id}")
    if status >= 400:
        return JSONResponse(content={"detail": text}, status_code=status)
    return Response(status_code=204)


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
