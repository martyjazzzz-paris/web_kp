"""Mail + LLM integration config checks (no secrets in responses)."""

from __future__ import annotations

import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass

import httpx

from bootstrap_env import load_project_env

load_project_env()


@dataclass
class CheckResult:
    ok: bool
    detail: str


def integration_status() -> dict:
    imap_user = os.getenv("IMAP_USER", "").strip()
    imap_password = os.getenv("IMAP_PASSWORD", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    yandex_key = os.getenv("YANDEX_API_KEY", "").strip()
    yandex_folder = os.getenv("YANDEX_FOLDER_ID", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower()

    return {
        "llm_provider": llm_provider or "(auto)",
        "mail": {
            "imap_configured": bool(imap_user and imap_password),
            "imap_user": imap_user or None,
            "smtp_configured": bool(smtp_user and smtp_password),
            "smtp_user": smtp_user or None,
        },
        "yandex_gpt": {
            "api_key_configured": bool(yandex_key),
            "folder_id_configured": bool(yandex_folder),
            "model": os.getenv("YANDEX_MODEL", "yandexgpt-lite").strip(),
        },
        "openai": {"api_key_configured": bool(openai_key)},
        "ready_for_ingest": bool(imap_user and imap_password),
        "ready_for_yandex_llm": bool(yandex_key and yandex_folder),
        "ready_for_openai_llm": bool(openai_key),
    }


def check_imap() -> CheckResult:
    host = os.getenv("IMAP_HOST", "imap.mail.ru").strip()
    port = int(os.getenv("IMAP_PORT", "993"))
    user = os.getenv("IMAP_USER", "").strip()
    password = os.getenv("IMAP_PASSWORD", "").strip()
    if not user or not password:
        return CheckResult(False, "IMAP_USER или IMAP_PASSWORD не заданы в .env")
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=20) as client:
            client.login(user, password)
            client.select("INBOX")
        return CheckResult(True, f"IMAP OK ({user}@{host})")
    except Exception as exc:
        return CheckResult(False, f"IMAP: {exc}")


def check_smtp() -> CheckResult:
    from smtp_client import check_connection, test_login

    tcp_ok, tcp_detail = check_connection()
    if not tcp_ok:
        return CheckResult(False, f"SMTP TCP: {tcp_detail}")

    login_ok, login_detail = test_login()
    if not login_ok:
        return CheckResult(False, f"SMTP login: {login_detail} ({tcp_detail})")
    return CheckResult(True, f"{login_detail}. {tcp_detail}")


def check_yandex_gpt() -> CheckResult:
    api_key = os.getenv("YANDEX_API_KEY", "").strip()
    folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip()
    model = os.getenv("YANDEX_MODEL", "yandexgpt-lite").strip()
    url = os.getenv(
        "YANDEX_API_URL",
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
    ).strip()

    if not api_key:
        return CheckResult(
            False,
            "YANDEX_API_KEY не задан (это API-ключ Yandex Cloud, не YANDEX_TOKEN с Диска)",
        )
    if not folder_id:
        return CheckResult(
            False,
            "YANDEX_FOLDER_ID не задан (ID каталога в Yandex Cloud, например b1g...)",
        )

    payload = {
        "modelUri": f"gpt://{folder_id}/{model}/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": 16},
        "messages": [{"role": "user", "text": "Ответь одним словом: ок"}],
    }
    headers = {"Authorization": f"Api-Key {api_key}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return CheckResult(True, f"Yandex GPT OK (model {model})")
        return CheckResult(False, f"Yandex GPT HTTP {response.status_code}: {response.text[:200]}")
    except Exception as exc:
        return CheckResult(False, f"Yandex GPT: {exc}")


def run_all_checks() -> dict:
    imap = check_imap()
    smtp = check_smtp()
    yandex = check_yandex_gpt()
    status = integration_status()
    return {
        "status": status,
        "checks": {
            "imap": {"ok": imap.ok, "detail": imap.detail},
            "smtp": {"ok": smtp.ok, "detail": smtp.detail},
            "yandex_gpt": {"ok": yandex.ok, "detail": yandex.detail},
        },
        "all_ok": imap.ok and smtp.ok and yandex.ok,
    }
