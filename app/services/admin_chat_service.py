"""Админ-чат: разбор slash-команд и агент, помогающий админу наполнять чат клиента контентом."""
import re
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_client import chat_once
from app.models import GalleryItem
from app.services.file_service import list_user_files, set_file_trigger
from app.services.gallery_service import (
    list_galleries,
    create_gallery,
    delete_gallery,
    add_file_to_gallery,
    remove_from_gallery,
)
from app.services.prompt_loader import load_admin_prompt

# Fallback, если файл промпта недоступен
ADMIN_SYSTEM_PROMPT_FALLBACK = """Ты — помощник администратора личного кабинета. Администратор управляет файлами и галереями через команды: /help, /files, /trigger, /gallery. Подскажи команды или ответь на вопрос о кабинете."""


def _get_admin_prompt() -> str:
    try:
        return load_admin_prompt()
    except FileNotFoundError:
        return ADMIN_SYSTEM_PROMPT_FALLBACK


async def _cmd_help() -> str:
    return (
        "Команды:\n"
        "/files — список файлов\n"
        "/trigger <file_id> <фраза> — привязать триггер к файлу\n"
        "/trigger clear <file_id> — убрать триггер\n"
        "/gallery list — список галерей\n"
        "/gallery create <название> — создать галерею\n"
        "/gallery add <gallery_id> <file_id> — добавить файл в галерею\n"
        "/gallery remove <gallery_id> <item_id> — убрать из галереи\n"
        "/gallery delete <gallery_id> — удалить галерею\n"
        "/help — эта справка"
    )


async def _cmd_files(db: AsyncSession, tenant_id: UUID, user_id: str) -> str:
    _, items = await list_user_files(db, tenant_id, user_id, limit=100, offset=0)
    if not items:
        return "Файлов пока нет. Загрузите их в разделе «Файлы»."
    lines = []
    for uf in items:
        trigger = f" триггер: «{uf.trigger}»" if uf.trigger else ""
        lines.append(f"- {uf.id} | {uf.filename}{trigger}")
    return "Файлы:\n" + "\n".join(lines)


async def _cmd_trigger(
    db: AsyncSession, tenant_id: UUID, user_id: str, args: list[str],
) -> str:
    if len(args) < 1:
        return "Использование: /trigger <file_id> <фраза> или /trigger clear <file_id>"
    if args[0].lower() == "clear":
        if len(args) < 2:
            return "Укажите file_id: /trigger clear <file_id>"
        try:
            file_id = UUID(args[1])
        except ValueError:
            return "Неверный file_id."
        uf = await set_file_trigger(db, tenant_id, user_id, file_id, None)
        if not uf:
            return "Файл не найден."
        return f"Триггер у файла «{uf.filename}» убран."
    try:
        file_id = UUID(args[0])
    except ValueError:
        return "Неверный file_id."
    phrase = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not phrase:
        return "Укажите фразу: /trigger <file_id> <фраза>"
    uf = await set_file_trigger(db, tenant_id, user_id, file_id, phrase[:128])
    if not uf:
        return "Файл не найден."
    return f"Триггер «{phrase}» привязан к файлу «{uf.filename}»."


async def _cmd_gallery(
    db: AsyncSession, tenant_id: UUID, user_id: str, args: list[str],
) -> str:
    if not args:
        return "Использование: /gallery list | create <name> | add <gallery_id> <file_id> | remove <gallery_id> <item_id> | delete <gallery_id>"
    sub = args[0].lower()
    if sub == "list":
        galleries = await list_galleries(db, tenant_id, user_id)
        if not galleries:
            return "Галерей пока нет. Создайте: /gallery create <название>"
        lines = []
        for g in galleries:
            cnt = await db.execute(
                select(func.count()).select_from(GalleryItem).where(GalleryItem.gallery_id == g.id)
            )
            n = cnt.scalar() or 0
            lines.append(f"- {g.id} | {g.name} ({n} фото)")
        return "Галереи:\n" + "\n".join(lines)
    if sub == "create":
        name = " ".join(args[1:]).strip() if len(args) > 1 else "Галерея"
        if not name:
            return "Укажите название: /gallery create <название>"
        g = await create_gallery(db, tenant_id, user_id, name[:256])
        return f"Галерея «{g.name}» создана. id: {g.id}"
    if sub == "add":
        if len(args) < 3:
            return "Использование: /gallery add <gallery_id> <file_id>"
        try:
            gallery_id = UUID(args[1])
            file_id = UUID(args[2])
        except ValueError:
            return "Неверные id."
        item = await add_file_to_gallery(db, tenant_id, user_id, gallery_id, file_id)
        if not item:
            return "Галерея или файл не найдены."
        return "Файл добавлен в галерею."
    if sub == "remove":
        if len(args) < 3:
            return "Использование: /gallery remove <gallery_id> <item_id>"
        try:
            gallery_id = UUID(args[1])
            item_id = UUID(args[2])
        except ValueError:
            return "Неверные id."
        ok = await remove_from_gallery(db, tenant_id, user_id, gallery_id, item_id)
        if not ok:
            return "Элемент или галерея не найдены."
        return "Файл убран из галереи."
    if sub == "delete":
        if len(args) < 2:
            return "Укажите gallery_id: /gallery delete <gallery_id>"
        try:
            gallery_id = UUID(args[1])
        except ValueError:
            return "Неверный gallery_id."
        ok = await delete_gallery(db, tenant_id, user_id, gallery_id)
        if not ok:
            return "Галерея не найдена."
        return "Галерея удалена."
    return "Подкоманда: list | create | add | remove | delete"


async def handle_admin_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    message: str,
) -> str:
    """
    Обрабатывает сообщение админа: если начинается с / — выполняет команду,
    иначе отправляет в LLM с системным промптом про команды.
    """
    text = (message or "").strip()
    if not text:
        return "Напишите команду (начните с /) или вопрос. /help — справка."

    if not text.startswith("/"):
        system_prompt = _get_admin_prompt()
        reply = await chat_once(
            system_prompt,
            [{"role": "user", "content": text}],
        )
        return reply.strip()

    parts = re.split(r"\s+", text, maxsplit=1)
    cmd = parts[0].lower()
    args = re.split(r"\s+", parts[1].strip()) if len(parts) > 1 and parts[1].strip() else []

    if cmd == "/help":
        return await _cmd_help()
    if cmd == "/files":
        return await _cmd_files(db, tenant_id, user_id)
    if cmd == "/trigger":
        return await _cmd_trigger(db, tenant_id, user_id, args)
    if cmd == "/gallery":
        return await _cmd_gallery(db, tenant_id, user_id, args)

    return "Неизвестная команда. /help — справка."
