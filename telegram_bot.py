from __future__ import annotations

from bootstrap_env import load_project_env

load_project_env()

import json
import os
import asyncio
import random
from datetime import datetime
from io import BytesIO

from telegram import BotCommand, ReplyKeyboardMarkup, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from db import get_session, init_db
from mail_ingest import ingest_unseen_emails_detail
from models import InboundEmail, QuoteDraft
from review_routes import approve_draft, reject_draft

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://72.56.237.74").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_admin_ids_raw = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()
TELEGRAM_ADMIN_IDS = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()}

BTN_INGEST = "📥 Забрать письма"
BTN_DRAFTS = "📋 ВХОДЯЩИЕ"
BTN_HELP = "ℹ️ Помощь"
BTN_WEB = "🌐 Открыть web-ревью"
BTN_HEALTH = "❤️ Health"


def _menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_INGEST, BTN_DRAFTS], [BTN_WEB, BTN_HEALTH], [BTN_HELP]],
        resize_keyboard=True,
        is_persistent=True,
    )


def _is_admin(user_id: int) -> bool:
    return bool(TELEGRAM_ADMIN_IDS) and user_id in TELEGRAM_ADMIN_IDS


async def _reply_text_safe(update: Update, text: str, reply_markup=None) -> None:
    if not update.message:
        return
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            await update.message.reply_text(text, reply_markup=reply_markup)
            return
        except (TimedOut, NetworkError) as exc:
            last_exc = exc
            await asyncio.sleep((1.2**attempt) + random.uniform(0.0, 0.4))
    if last_exc:
        print(f"reply_text failed after retries: {last_exc}")


async def _reply_document_safe(update: Update, document, filename: str, caption: str = "") -> None:
    if not update.message:
        return
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            if hasattr(document, "seek"):
                document.seek(0)
            await update.message.reply_document(document=document, filename=filename, caption=caption)
            return
        except (TimedOut, NetworkError) as exc:
            last_exc = exc
            await asyncio.sleep((1.2**attempt) + random.uniform(0.0, 0.4))
    if last_exc:
        print(f"reply_document failed after retries: {last_exc}")


async def _guard(update: Update) -> bool:
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await _reply_text_safe(update, "Доступ запрещен.")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    text = (
        "Управление КП ботом.\n\n"
        "Команды:\n"
        "/ingest - забрать новые письма\n"
        "/drafts - список последних черновиков\n"
        "/draft <id> - детали черновика\n"
        "/pdf <id> - PDF превью черновика\n"
        "/approve <id> - подтвердить и отправить клиенту\n"
        "/reject <id> <причина> - отклонить черновик"
    )
    await _reply_text_safe(update, text, reply_markup=_menu_keyboard())


async def cmd_ingest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    result = ingest_unseen_emails_detail(limit=20)
    if result.error:
        await _reply_text_safe(update, f"Ошибка почты:\n{result.error}")
        return
    await _reply_text_safe(update, f"Готово: забрано новых писем: {result.ingested}")


async def cmd_drafts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    with get_session() as session:
        rows = (
            session.query(QuoteDraft, InboundEmail)
            .join(InboundEmail, InboundEmail.id == QuoteDraft.inbound_email_id)
            .order_by(QuoteDraft.created_at.desc())
            .limit(10)
            .all()
        )
    if not rows:
        await _reply_text_safe(update, "Черновиков пока нет.")
        return
    parts = []
    for d, e in rows:
        created = d.created_at.strftime("%d.%m %H:%M")
        parts.append(f"#{d.id} [{d.status}] conf={d.confidence:.2f} | {created}\n{e.subject or '-'}")
    await _reply_text_safe(update, "\n\n".join(parts))


async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args or not context.args[0].isdigit():
        await _reply_text_safe(update, "Использование: /draft <id>")
        return
    draft_id = int(context.args[0])
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            await _reply_text_safe(update, "Черновик не найден.")
            return
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()

    rows_summary = []
    try:
        parsed_payload = json.loads(draft.parsed_json or "{}")
    except Exception:
        parsed_payload = {}
    for row in parsed_payload.get("rows", [])[:8]:
        if not isinstance(row, dict):
            continue
        item = str(row.get("item_name", "")).strip() or "Позиция"
        qty = row.get("qty", 0)
        price = row.get("price", 0)
        rows_summary.append(f"- {item}: {qty} x {price}")
    rows_text = "\n".join(rows_summary) if rows_summary else "- Позиции не распознаны"
    body_short = ((email_row.body_text if email_row else "") or "").strip()
    if len(body_short) > 1200:
        body_short = body_short[:1200] + "..."

    msg = (
        f"Черновик #{draft.id}\n"
        f"Статус: {draft.status}\n"
        f"Уверенность: {draft.confidence:.2f}\n"
        f"Отправитель: {(email_row.sender_email if email_row else '-')}\n"
        f"Тема: {(email_row.subject if email_row else '-')}\n"
        f"Создан: {draft.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"\nПозиции:\n{rows_text}\n"
        f"\nТекст письма:\n{body_short or '-'}\n"
        f"Ссылка: {PUBLIC_BASE_URL}/review/ui/{draft.id}"
    )
    await _reply_text_safe(update, msg)


async def cmd_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args or not context.args[0].isdigit():
        await _reply_text_safe(update, "Использование: /pdf <id>")
        return
    draft_id = int(context.args[0])
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            await _reply_text_safe(update, "Черновик не найден.")
            return
        try:
            parsed_payload = json.loads(draft.parsed_json or "{}")
        except Exception:
            parsed_payload = {}
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()

    from main import build_pdf
    from review_routes import _apply_hard_qty_rules, _build_offer_from_draft_payload

    parsed_payload = _apply_hard_qty_rules(parsed_payload, (email_row.body_text if email_row else "") or "")
    offer = _build_offer_from_draft_payload(parsed_payload)
    if offer is None:
        await _reply_text_safe(update, "Не удалось собрать PDF: нет валидных позиций.")
        return

    pdf_bytes = build_pdf(offer)
    stream = BytesIO(pdf_bytes)
    stream.name = f"draft_{draft_id}.pdf"
    stream.seek(0)
    await _reply_document_safe(update, stream, stream.name, caption=f"Черновик #{draft_id}")


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args or not context.args[0].isdigit():
        await _reply_text_safe(update, "Использование: /approve <id>")
        return
    draft_id = int(context.args[0])
    try:
        result = await approve_draft(draft_id)
    except Exception as exc:
        await _reply_text_safe(update, f"Ошибка approve: {exc}")
        return
    if result.get("ok"):
        await _reply_text_safe(update, f"Готово. КП отправлено: {result.get('sent_to', '-')}")
    else:
        await _reply_text_safe(update, f"Не удалось подтвердить: {result}")


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args or not context.args[0].isdigit():
        await _reply_text_safe(update, "Использование: /reject <id> <причина>")
        return
    draft_id = int(context.args[0])
    reason = " ".join(context.args[1:]).strip()
    await reject_draft(draft_id, reason)
    await _reply_text_safe(update, f"Черновик #{draft_id} отклонен.")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    try:
        with get_session() as session:
            drafts_total = session.query(QuoteDraft).count()
            pending_total = session.query(QuoteDraft).filter(QuoteDraft.status == "pending").count()
        payload = (
            "✅ Bot health: OK\n"
            f"UTC: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"Черновиков всего: {drafts_total}\n"
            f"Ожидают review: {pending_total}"
        )
    except Exception as exc:
        payload = f"⚠️ Bot health: DB error\n{exc}"
    await _reply_text_safe(update, payload)


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    message_text = (update.message.text or "").strip()
    if message_text == BTN_INGEST:
        await cmd_ingest(update, context)
        return
    if message_text == BTN_DRAFTS:
        await cmd_drafts(update, context)
        return
    if message_text == BTN_WEB:
        await _reply_text_safe(update, f"Откройте: {PUBLIC_BASE_URL}/review/ui")
        return
    if message_text == BTN_HEALTH:
        await cmd_health(update, context)
        return
    if message_text == BTN_HELP:
        await cmd_start(update, context)
        return


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Меню и справка"),
            BotCommand("ingest", "Забрать новые письма"),
            BotCommand("drafts", "Список черновиков"),
            BotCommand("draft", "Показать черновик по ID"),
            BotCommand("pdf", "PDF черновика по ID"),
            BotCommand("approve", "Подтвердить черновик по ID"),
            BotCommand("reject", "Отклонить черновик по ID"),
            BotCommand("health", "Проверка статуса бота"),
        ]
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        print(f"[{datetime.utcnow().isoformat()}] transient telegram error: {err}")
        return
    print(f"[{datetime.utcnow().isoformat()}] bot error: {err}")


async def cmd_health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_health(update, context)


def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    if not TELEGRAM_ADMIN_IDS:
        raise RuntimeError("TELEGRAM_ADMIN_IDS is missing")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(20.0)
        .read_timeout(70.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ingest", cmd_ingest))
    app.add_handler(CommandHandler("drafts", cmd_drafts))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("pdf", cmd_pdf))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("health", cmd_health_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_menu_click))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    init_db()
    restart_delay = 5
    while True:
        try:
            app = build_app()
            print(f"[{datetime.utcnow().isoformat()}] Telegram bot started")
            app.run_polling(drop_pending_updates=False, bootstrap_retries=-1, timeout=50)
            print(f"[{datetime.utcnow().isoformat()}] Telegram bot stopped gracefully")
            break
        except KeyboardInterrupt:
            print(f"[{datetime.utcnow().isoformat()}] Telegram bot stopped by keyboard interrupt")
            break
        except Exception as exc:
            print(f"[{datetime.utcnow().isoformat()}] polling crashed: {exc}; restart in {restart_delay}s")
            asyncio.run(asyncio.sleep(restart_delay))
            restart_delay = min(60, restart_delay + 5)


if __name__ == "__main__":
    main()
