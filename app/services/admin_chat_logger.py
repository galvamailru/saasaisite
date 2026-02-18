"""Логирование диалогов админ-бота в файлы: одна сессия — один файл.
Формат: вопрос пользователя, строка из символов #, ответ бота."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import PROJECT_ROOT, settings

SEP_LINE = "#" * 60


def _log_dir() -> Path:
    p = Path(settings.admin_chat_log_dir)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _session_log_path(tenant_id: UUID, session_id: str) -> Path:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_sid = "".join(c for c in session_id if c.isalnum() or c == "-")
    return log_dir / f"{tenant_id}_{safe_sid}.log"


def append_admin_chat_exchange(
    tenant_id: UUID,
    session_id: str,
    user_message: str,
    assistant_reply: str,
    *,
    is_new_session: bool = False,
) -> None:
    """
    Пишет в лог-файл сессии одну пару вопрос–ответ.
    is_new_session: True для первого сообщения в сессии (добавляется заголовок).
    """
    path = _session_log_path(tenant_id, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    block = (
        f"user:\n{user_message}\n{SEP_LINE}\nassistant:\n{assistant_reply}\n"
    )
    if is_new_session:
        header = f"tenant_id={tenant_id} session_id={session_id} started={ts}\n{SEP_LINE}\n"
        content = header + block
    else:
        content = "\n" + block
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass  # не падаем при ошибках записи (диск, права)
