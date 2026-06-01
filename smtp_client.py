"""SMTP send with IPv4 and SSL/STARTTLS fallbacks (fixes Docker errno 113)."""

from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
from collections.abc import Callable
from email.message import EmailMessage

from bootstrap_env import load_project_env

load_project_env()

logger = logging.getLogger(__name__)


def smtp_settings() -> dict[str, str | int]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip() or os.getenv("MAIL_SMTP", "").strip(),
        "port_ssl": int(os.getenv("SMTP_PORT", "465")),
        "port_starttls": int(os.getenv("SMTP_PORT_STARTTLS", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_addr": os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")).strip(),
        "timeout": float(os.getenv("SMTP_TIMEOUT_SECONDS", "25")),
    }


def validate_smtp_config() -> None:
    cfg = smtp_settings()
    missing = [k for k in ("host", "user", "password", "from_addr") if not cfg[k]]
    if missing:
        raise RuntimeError(
            "SMTP не настроен. Заполните SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM в .env"
        )


def _resolve_ipv4(host: str, port: int) -> tuple[str, int]:
    try:
        infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError(f"Не удалось разрешить SMTP-хост {host!r}: {exc}") from exc
    if not infos:
        raise OSError(
            f"Нет IPv4-адреса для {host}:{port}. "
            "На VPS без IPv6 это даёт «No route to host» — используем принудительно IPv4."
        )
    sockaddr = infos[0][4]
    return sockaddr[0], sockaddr[1]


def _send_ssl_ipv4(
    host: str,
    port: int,
    user: str,
    password: str,
    message: EmailMessage,
    timeout: float,
) -> None:
    addr = _resolve_ipv4(host, port)
    context = ssl.create_default_context()
    logger.info("SMTP SSL connect %s:%s (IPv4 %s:%s)", host, port, addr[0], addr[1])
    with socket.create_connection(addr, timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            client = smtplib.SMTP()
            client.sock = ssock
            client.file = ssock.makefile("rb")
            client._host = host  # noqa: SLF001
            try:
                client.ehlo_or_helo_if_needed()
                client.login(user, password)
                client.send_message(message)
            finally:
                try:
                    client.quit()
                except Exception:
                    pass


def _send_starttls_ipv4(
    host: str,
    port: int,
    user: str,
    password: str,
    message: EmailMessage,
    timeout: float,
) -> None:
    addr = _resolve_ipv4(host, port)
    context = ssl.create_default_context()
    logger.info("SMTP STARTTLS connect %s:%s (IPv4 %s:%s)", host, port, addr[0], addr[1])
    with socket.create_connection(addr, timeout=timeout) as sock:
        client = smtplib.SMTP()
        client.sock = sock
        client.file = sock.makefile("rb")
        client._host = host  # noqa: SLF001
        try:
            client.ehlo_or_helo_if_needed()
            client.starttls(context=context)
            client.ehlo_or_helo_if_needed()
            client.login(user, password)
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                pass


def send_message(message: EmailMessage) -> str:
    """Send email; returns label of method used. Raises on failure."""
    validate_smtp_config()
    cfg = smtp_settings()
    host = str(cfg["host"])
    user = str(cfg["user"])
    password = str(cfg["password"])
    timeout = float(cfg["timeout"])
    port_ssl = int(cfg["port_ssl"])
    port_starttls = int(cfg["port_starttls"])

    attempts: list[tuple[str, Callable[[], None]]] = [
        (f"SSL:{port_ssl}", lambda: _send_ssl_ipv4(host, port_ssl, user, password, message, timeout)),
        (
            f"STARTTLS:{port_starttls}",
            lambda: _send_starttls_ipv4(host, port_starttls, user, password, message, timeout),
        ),
    ]

    errors: list[str] = []
    for label, fn in attempts:
        try:
            fn()
            return label
        except OSError as exc:
            errno = getattr(exc, "errno", None)
            hint = ""
            if errno == 113:
                hint = " (нет маршрута до хоста — часто IPv6/фаервол VPS; пробуем другой порт)"
            errors.append(f"{label}: {exc}{hint}")
            logger.warning("SMTP attempt failed %s: %s", label, exc)
        except smtplib.SMTPException as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("SMTP attempt failed %s: %s", label, exc)

    raise OSError("SMTP: " + " | ".join(errors))


def check_connection() -> tuple[bool, str]:
    try:
        validate_smtp_config()
        cfg = smtp_settings()
        host = str(cfg["host"])
        port_ssl = int(cfg["port_ssl"])
        addr = _resolve_ipv4(host, port_ssl)
        with socket.create_connection(addr, timeout=float(cfg["timeout"])):
            pass
        return True, f"TCP OK → {host}:{port_ssl} via {addr[0]}"
    except Exception as exc:
        return False, str(exc)


def _login_ssl_ipv4(host: str, port: int, user: str, password: str, timeout: float) -> None:
    addr = _resolve_ipv4(host, port)
    context = ssl.create_default_context()
    with socket.create_connection(addr, timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            client = smtplib.SMTP()
            client.sock = ssock
            client.file = ssock.makefile("rb")
            client._host = host  # noqa: SLF001
            try:
                client.ehlo_or_helo_if_needed()
                client.login(user, password)
                client.noop()
            finally:
                try:
                    client.quit()
                except Exception:
                    pass


def _login_starttls_ipv4(host: str, port: int, user: str, password: str, timeout: float) -> None:
    addr = _resolve_ipv4(host, port)
    context = ssl.create_default_context()
    with socket.create_connection(addr, timeout=timeout) as sock:
        client = smtplib.SMTP()
        client.sock = sock
        client.file = sock.makefile("rb")
        client._host = host  # noqa: SLF001
        try:
            client.ehlo_or_helo_if_needed()
            client.starttls(context=context)
            client.ehlo_or_helo_if_needed()
            client.login(user, password)
            client.noop()
        finally:
            try:
                client.quit()
            except Exception:
                pass


def test_login() -> tuple[bool, str]:
    """Verify SMTP credentials without sending mail."""
    try:
        validate_smtp_config()
    except RuntimeError as exc:
        return False, str(exc)

    cfg = smtp_settings()
    host = str(cfg["host"])
    user = str(cfg["user"])
    password = str(cfg["password"])
    timeout = float(cfg["timeout"])
    errors: list[str] = []
    for label, fn in (
        (f"SSL:{cfg['port_ssl']}", lambda: _login_ssl_ipv4(host, int(cfg["port_ssl"]), user, password, timeout)),
        (
            f"STARTTLS:{cfg['port_starttls']}",
            lambda: _login_starttls_ipv4(host, int(cfg["port_starttls"]), user, password, timeout),
        ),
    ):
        try:
            fn()
            return True, f"Login OK ({user}@{host}, {label})"
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    return False, " | ".join(errors)
