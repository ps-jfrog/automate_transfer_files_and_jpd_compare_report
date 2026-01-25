from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from jfrog_transfer_automation.config.model import EmailConfig


def send_email(config: EmailConfig, subject: str, body: str) -> None:
    password = os.environ.get(config.smtp_password_env, "")
    if not config.smtp_host or not config.smtp_user or not password:
        raise RuntimeError("Email config is incomplete")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(config.to)
    message.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
        server.starttls()
        server.login(config.smtp_user, password)
        server.send_message(message)
