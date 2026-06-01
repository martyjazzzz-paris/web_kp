from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from dataclasses import dataclass
from html import unescape
from email.header import decode_header
from email.utils import parseaddr

from bootstrap_env import load_project_env

load_project_env()

from ai_parser import parse_inbound_email
from db import get_session
from draft_builder import parsed_to_json
from models import InboundEmail, QuoteDraft

logger = logging.getLogger(__name__)

IMAP_HOST = os.getenv("IMAP_HOST", "imap.mail.ru")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "").strip()
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "").strip()


@dataclass
class IngestResult:
    ingested: int = 0
    ingested_ids: list[int] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.ingested_ids is None:
            self.ingested_ids = []

    @property
    def ok(self) -> bool:
        return self.error is None


def _decode_mime(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _decode_payload_bytes(payload: bytes, declared_charset: str | None) -> str:
    charsets = [declared_charset, "utf-8", "cp1251", "koi8-r", "windows-1251", "latin-1"]
    tried = set()
    for charset in charsets:
        if not charset:
            continue
        key = charset.lower().strip()
        if key in tried:
            continue
        tried.add(key)
        try:
            return payload.decode(charset)
        except Exception:
            continue
    return payload.decode("utf-8", errors="ignore")


def _html_to_text(html: str) -> str:
    text = html or ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _clean_mail_text(text: str) -> str:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    split_markers = [
        r"\n[-]{2,}\s*Исходное сообщение\s*[-]{2,}",
        r"\nOn .+wrote:\s*$",
        r"\nFrom:\s.+\nSent:\s.+\nTo:\s.+\nSubject:\s.+",
    ]
    for marker in split_markers:
        m = re.search(marker, value, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            value = value[: m.start()]
            break
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _extract_body(msg: email.message.Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            payload = part.get_payload(decode=True) or b""
            if not payload:
                continue
            decoded = _decode_payload_bytes(payload, part.get_content_charset())
            if ctype == "text/plain":
                plain_parts.append(decoded)
            elif ctype == "text/html":
                html_parts.append(_html_to_text(decoded))
    else:
        payload = msg.get_payload(decode=True) or b""
        decoded = _decode_payload_bytes(payload, msg.get_content_charset())
        if msg.get_content_type() == "text/html":
            html_parts.append(_html_to_text(decoded))
        else:
            plain_parts.append(decoded)

    body = "\n\n".join(part for part in plain_parts if part.strip()).strip()
    if not body:
        body = "\n\n".join(part for part in html_parts if part.strip()).strip()
    return _clean_mail_text(body)


def ingest_unseen_emails(limit: int = 10) -> int:
    return ingest_unseen_emails_detail(limit).ingested


def ingest_unseen_emails_detail(limit: int = 10) -> IngestResult:
    if not IMAP_USER or not IMAP_PASSWORD:
        msg = "Почта не настроена: укажите IMAP_USER и IMAP_PASSWORD (пароль приложения Mail.ru) в .env"
        logger.warning(msg)
        return IngestResult(ingested=0, error=msg)

    count = 0
    ingested_ids: list[int] = []
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as client:
            client.login(IMAP_USER, IMAP_PASSWORD)
            client.select("INBOX")
            typ, data = client.search(None, "UNSEEN")
            if typ != "OK":
                return IngestResult(ingested=0, error="IMAP: не удалось выполнить поиск UNSEEN")

            ids = data[0].split()[:limit]

            with get_session() as session:
                for msg_id in ids:
                    typ, msg_data = client.fetch(msg_id, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    message_id = _decode_mime(msg.get("Message-ID")) or f"msg-{msg_id.decode()}"
                    exists = session.query(InboundEmail).filter(InboundEmail.message_id == message_id).first()
                    if exists:
                        continue

                    subject = _decode_mime(msg.get("Subject"))
                    sender = parseaddr(msg.get("From") or "")[1]
                    body = _extract_body(msg)

                    inbound = InboundEmail(
                        message_id=message_id,
                        sender_email=sender,
                        subject=subject,
                        body_text=body,
                    )
                    session.add(inbound)
                    session.flush()

                    parsed = parse_inbound_email(subject, body)
                    draft = QuoteDraft(
                        inbound_email_id=inbound.id,
                        status="ready_for_review" if parsed.confidence >= 0.5 else "needs_clarification",
                        confidence=parsed.confidence,
                        parsed_json=parsed_to_json(parsed.payload),
                        note=parsed.note,
                    )
                    session.add(draft)
                    session.flush()
                    ingested_ids.append(int(draft.id))
                    count += 1

                session.commit()
    except Exception as exc:
        logger.exception("Mail ingest failed")
        return IngestResult(ingested=0, ingested_ids=[], error=str(exc))

    return IngestResult(ingested=count, ingested_ids=ingested_ids)
