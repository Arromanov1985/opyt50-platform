"""Production email transport with an explicit safe fallback.

No credentials are stored in the repository. External delivery is enabled only when
OPYT50_SMTP_HOST and OPYT50_MAIL_FROM are configured in the runtime environment.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def delivery_mode() -> str:
    return "smtp" if os.getenv("OPYT50_SMTP_HOST", "").strip() and os.getenv("OPYT50_MAIL_FROM", "").strip() else "outbox_only"


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send one UTF-8 message when SMTP is configured.

    Returns False when delivery is disabled or fails. Mail failures never expose
    credentials or reset/verification tokens in application logs.
    """
    host = os.getenv("OPYT50_SMTP_HOST", "").strip()
    sender = os.getenv("OPYT50_MAIL_FROM", "").strip()
    if not host or not sender:
        return False

    try:
        port = int(os.getenv("OPYT50_SMTP_PORT", "587"))
    except ValueError:
        logger.error("Email delivery configuration error: invalid SMTP port")
        return False

    username = os.getenv("OPYT50_SMTP_USER", "").strip()
    password = os.getenv("OPYT50_SMTP_PASSWORD", "")
    use_ssl = os.getenv("OPYT50_SMTP_SSL", "0") == "1"
    use_starttls = os.getenv("OPYT50_SMTP_STARTTLS", "1") == "1"

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context()) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if use_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("Email delivery failed for event recipient")
        return False
