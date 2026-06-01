"""Load environment from project root and web_kp/.env with integration aliases."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

WEB_KP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_KP_DIR.parent


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _set_if_missing(key: str, value: str) -> None:
    if value and not os.getenv(key, "").strip():
        os.environ[key] = value


def _apply_integration_aliases() -> None:
    """Map legacy / shared names to web_kp integration variables."""
    mail_user = _first_env("IMAP_USER", "SMTP_USER", "MAIL_USER")
    mail_password = _first_env("IMAP_PASSWORD", "SMTP_PASSWORD", "MAIL_PASSWORD")

    _set_if_missing("IMAP_USER", mail_user)
    _set_if_missing("SMTP_USER", mail_user)
    _set_if_missing("MAIL_USER", mail_user)

    _set_if_missing("IMAP_PASSWORD", mail_password)
    _set_if_missing("SMTP_PASSWORD", mail_password)
    _set_if_missing("MAIL_PASSWORD", mail_password)

    _set_if_missing("SMTP_FROM", _first_env("SMTP_FROM", "MAIL_FROM", "SMTP_USER"))
    _set_if_missing("MAIL_FROM", _first_env("MAIL_FROM", "SMTP_FROM", "SMTP_USER"))

    _set_if_missing("SMTP_HOST", _first_env("SMTP_HOST", "MAIL_SMTP"))
    _set_if_missing("IMAP_HOST", _first_env("IMAP_HOST", "imap.mail.ru"))

    yandex_api_key = _first_env("YANDEX_API_KEY", "YANDEX_GPT_API_KEY")
    yandex_folder_id = _first_env("YANDEX_FOLDER_ID", "YANDEX_CLOUD_FOLDER_ID", "YANDEX_GPT_FOLDER_ID")

    _set_if_missing("YANDEX_API_KEY", yandex_api_key)
    _set_if_missing("YANDEX_FOLDER_ID", yandex_folder_id)

    if not os.getenv("LLM_PROVIDER", "").strip():
        if yandex_api_key and yandex_folder_id:
            os.environ["LLM_PROVIDER"] = "yandex"
        elif os.getenv("OPENAI_API_KEY", "").strip():
            os.environ["LLM_PROVIDER"] = "openai"


def load_project_env() -> None:
    """Root .env first, then web_kp/.env (overrides)."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(WEB_KP_DIR / ".env", override=True)
    _apply_integration_aliases()
