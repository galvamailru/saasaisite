"""Отправка писем (подтверждение регистрации). Конфиг из .env."""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from app.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        logger.warning(
            "SMTP не настроен (SMTP_HOST пустой). Письмо не отправлено, только в лог: To=%s Subject=%s",
            to,
            subject,
        )
        logger.debug("Текст письма: %s", body)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("CIP", settings.smtp_from))
    msg["To"] = to
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_user and settings.smtp_password:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_from, [to], msg.as_string())
        logger.info("Письмо отправлено: To=%s Subject=%s via %s:%s", to, subject, settings.smtp_host, settings.smtp_port)
    except Exception as e:
        logger.exception("Ошибка отправки письма To=%s: %s", to, e)
        raise


async def send_email(to: str, subject: str, body: str) -> None:
    await asyncio.get_event_loop().run_in_executor(None, _send_sync, to, subject, body)


async def send_confirmation_email(to: str, tenant_slug: str, token: str) -> None:
    base = settings.frontend_base_url.rstrip("/")
    url = f"{base}/{tenant_slug}/confirm?token={token}"
    subject = "Подтверждение регистрации"
    body = f"Перейдите по ссылке для подтверждения email:\n\n{url}\n\nСсылка действительна 24 часа."
    await send_email(to, subject, body)
