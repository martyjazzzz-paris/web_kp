from __future__ import annotations

import json
import re
from html import escape
from io import BytesIO

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import desc

from db import get_session
from mail_ingest import ingest_unseen_emails_detail
from models import InboundEmail, QuoteActionLog, QuoteDraft

router = APIRouter(prefix="/review", tags=["review"])

CASH_PRICE_BY_NOMENCLATURE = {
    "контейнер 20 футов бу": 55000.0,
    "контейнер 20 футов, высокий бу (20hc)": 75000.0,
    "контейнер 20 футов, новый бу (20hc)": 125000.0,
    "контейнер 20 футов новый": 175000.0,
    "контейнер 40 футов, стандартный бу": 85000.0,
    "контейнер 40 футов, стандартный новый": 140000.0,
    "контейнер 40 футов, высокий бу (40hc)": 80000.0,
    "контейнер 40 футов, высокий iicl (как новый)": 125000.0,
    "контейнер 40 футов, высокий новый": 170000.0,
}


def _guess_cash_price(item_name: str) -> float | None:
    key = (item_name or "").strip().lower().replace("ё", "е")
    if key in CASH_PRICE_BY_NOMENCLATURE:
        return CASH_PRICE_BY_NOMENCLATURE[key]
    return None


def _parse_num(value: object) -> float:
    raw = str(value or "").strip().replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _status_label(status: str) -> str:
    mapping = {
        "ready_for_review": "На проверке",
        "needs_clarification": "Нужны уточнения",
        "approved": "Подтвержден",
        "sent": "Отправлен",
        "rejected": "Отклонен",
    }
    return mapping.get((status or "").strip(), status or "-")


def _extract_forced_qty_from_text(text: str, size_hint: str) -> int | None:
    source = (text or "").lower().replace("ё", "е")
    if size_hint not in {"20", "40"}:
        return None
    patterns = [
        rf"(?:на|нужно|надо|требуется|необходимо)?\s*(\d+)\s*(?:шт\.?|штук|контейнер(?:а|ов)?)?\s*{size_hint}\s*(?:фут|ф|ft)",
        rf"{size_hint}\s*(?:фут|ф|ft)\s*(?:бу|нов(?:ый|ые)?)?.{{0,20}}?(?:на|нужно|надо|требуется)?\s*(\d+)",
        rf"(?:кол-?во|количество)\s*[:\-]?\s*(\d+).{{0,25}}?{size_hint}\s*(?:фут|ф|ft)",
    ]
    for pattern in patterns:
        m = re.search(pattern, source, flags=re.IGNORECASE)
        if not m:
            continue
        try:
            qty = int(m.group(1))
        except Exception:
            continue
        if qty > 0:
            return qty
    return None


def _apply_hard_qty_rules(parsed_payload: dict, email_text: str) -> dict:
    payload = dict(parsed_payload or {})
    rows = list(payload.get("rows") or [])
    if not rows:
        return payload
    combined_text = email_text or ""
    forced_20 = _extract_forced_qty_from_text(combined_text, "20")
    forced_40 = _extract_forced_qty_from_text(combined_text, "40")
    for row in rows:
        item = str(row.get("item_name", "")).lower()
        if "контейнер" not in item:
            continue
        if forced_20 and "20" in item:
            row["qty"] = float(forced_20)
        elif forced_40 and "40" in item:
            row["qty"] = float(forced_40)
    payload["rows"] = rows
    return payload


@router.post("/ingest")
async def trigger_ingest() -> dict:
    result = ingest_unseen_emails_detail(limit=200)
    if result.error:
        return {"ok": False, "ingested": result.ingested, "error": result.error}
    message = "Новых писем нет." if result.ingested == 0 else None
    return {
        "ok": True,
        "ingested": result.ingested,
        "ingested_ids": result.ingested_ids or [],
        "message": message,
    }


@router.get("/drafts")
async def list_drafts(limit: int = 50) -> dict:
    with get_session() as session:
        inbox_rows = (
            session.query(InboundEmail, QuoteDraft)
            .outerjoin(QuoteDraft, QuoteDraft.inbound_email_id == InboundEmail.id)
            .order_by(desc(InboundEmail.received_at), desc(InboundEmail.id))
            .limit(limit)
            .all()
        )
        items = [
            {
                "id": d.id if d else None,
                "status": (d.status if d else "no_draft"),
                "confidence": (d.confidence if d else 0),
                "sender_email": e.sender_email,
                "subject": e.subject,
                "created_at": (d.created_at.isoformat() if d else e.received_at.isoformat()),
                "note": (d.note if d else ""),
            }
            for e, d in inbox_rows
        ]
    return {"ok": True, "items": items}


@router.get("/ui", response_class=HTMLResponse)
async def drafts_ui(limit: int = 100) -> HTMLResponse:
    with get_session() as session:
        inbox_rows = (
            session.query(InboundEmail, QuoteDraft)
            .outerjoin(QuoteDraft, QuoteDraft.inbound_email_id == InboundEmail.id)
            .order_by(desc(InboundEmail.received_at), desc(InboundEmail.id))
            .limit(limit)
            .all()
        )
        draft_ids = [d.id for _, d in inbox_rows if d is not None]
        generator_sent_ids: set[int] = set()
        viewed_ids: set[int] = set()
        if draft_ids:
            gen_logs = (
                session.query(QuoteActionLog.draft_id)
                .filter(QuoteActionLog.draft_id.in_(draft_ids), QuoteActionLog.action == "generator_sent")
                .all()
            )
            generator_sent_ids = {draft_id for (draft_id,) in gen_logs}
            viewed_logs = (
                session.query(QuoteActionLog.draft_id)
                .filter(QuoteActionLog.draft_id.in_(draft_ids), QuoteActionLog.action == "viewed")
                .all()
            )
            viewed_ids = {draft_id for (draft_id,) in viewed_logs}

    rows = []
    row_no = 1
    for e, d in inbox_rows:
        has_draft = d is not None
        row_class = "draft-row-new" if has_draft and d.id not in viewed_ids else ""
        if has_draft:
            status_raw = escape(d.status or "")
            status_human = escape(_status_label(d.status or ""))
            status_cls = f"status-{(d.status or '').strip().replace('_', '-')}"
        else:
            status_raw = "no_draft"
            status_human = "Без черновика"
            status_cls = "status-needs-clarification"

        if has_draft and (d.status or "").strip() == "sent":
            reply_cls = "reply-sent"
            reply_label = "Отправлено"
        elif has_draft and d.id in generator_sent_ids:
            reply_cls = "reply-generator"
            reply_label = "Отправлено из генератора"
        elif has_draft:
            reply_cls = "reply-pending"
            reply_label = "Не отправлено"
        else:
            reply_cls = "reply-pending"
            reply_label = "Не обработано"

        sender_value = escape(e.sender_email or "")
        subject_value = escape(e.subject or "")
        if has_draft:
            action_html = (
                f'<a class="btn btn-surface btn-small inbox-action-btn" href="/review/ui/{d.id}">Ответить</a>'
            )
            checkbox_html = f'<input type="checkbox" name="draft_ids" value="{d.id}" />'
            confidence = f"{int((d.confidence or 0) * 100)}%" if (d.confidence or 0) > 0 else "—"
            created_at = d.created_at.strftime("%d.%m.%Y %H:%M")
        else:
            action_html = '<span class="hint">—</span>'
            checkbox_html = ""
            confidence = "—"
            created_at = e.received_at.strftime("%d.%m.%Y %H:%M")
        rows.append(
            f"""
            <tr class="{row_class}">
              <td>{checkbox_html}</td>
              <td>{row_no}</td>
              <td><span class="reply-chip {reply_cls}">{reply_label}</span></td>
              <td><span class="status-chip {status_cls}" title="{status_raw}">{status_human}</span></td>
              <td>{confidence}</td>
              <td class="inbox-cell inbox-cell--sender" title="{sender_value}">{sender_value}</td>
              <td class="inbox-cell inbox-cell--date">{created_at}</td>
              <td class="inbox-cell inbox-cell--subject" title="{subject_value}">{subject_value}</td>
              <td class="inbox-actions">{action_html}</td>
            </tr>
            """
        )
        row_no += 1

    html = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=1" />
  <link rel="stylesheet" href="/static/styles.css?v=81" />
  <title>ВХОДЯЩИЕ КП</title>
</head>
<body class="review-page">
  <header class="site-header">
    <div class="site-header__brand">
      <img src="/static/favicon.svg" alt="" class="site-header__logo" width="36" height="36" />
      <div>
        <h1>Входящие КП</h1>
        <p class="site-header__tagline">Почта и черновики</p>
      </div>
    </div>
    <nav class="site-header__nav">
      <a class="btn btn-tonal" href="/">Генератор</a>
    </nav>
  </header>
  <main class="container review-layout">
  <p class="review-layout__lead">Выберите входящие и работайте с ними как со списком задач. Новые письма выделены жирным.</p>
  <p id="ingest-list-note" class="hint"></p>
  <div class="actions">
    <button type="button" class="btn btn-small btn-surface" id="check-inbox-btn">Обновить почту</button>
    <form method="post" action="/review/ui/delete-selected" id="delete-selected-form">
      <button class="btn btn-small" type="submit">Удалить выбранные</button>
    </form>
  </div>
  <div class="review-table-wrap">
    <table id="drafts-table">
      <thead>
        <tr>
          <th><input type="checkbox" id="select-all-drafts" /></th><th>№</th><th>Ответ</th><th>Статус</th><th>Контекст</th><th>Отправитель</th><th>Создан</th><th>Тема</th><th>Действие</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="9">Входящих писем пока нет</td></tr>'}
      </tbody>
    </table>
  </div>
  </main>
  <script>
    const deleteForm = document.getElementById("delete-selected-form");
    const table = document.getElementById("drafts-table");
    const selectAll = document.getElementById("select-all-drafts");

    const checkInboxBtn = document.getElementById("check-inbox-btn");
    const ingestListNote = document.getElementById("ingest-list-note");
    if (checkInboxBtn) {{
      checkInboxBtn.addEventListener("click", async () => {{
        checkInboxBtn.disabled = true;
        if (ingestListNote) ingestListNote.textContent = "Забираем письма из почты...";
        try {{
          const response = await fetch("/review/ingest", {{ method: "POST" }});
          const data = await response.json().catch(() => ({{}}));
          if (!response.ok || !data.ok) {{
            throw new Error(data.error || "Не удалось проверить входящие");
          }}
          if (ingestListNote) {{
            ingestListNote.textContent = data.message || `Забрано новых писем: ${{data.ingested}}.`;
          }}
          if (data.ingested > 0) {{
            window.setTimeout(() => window.location.reload(), 600);
          }}
        }} catch (err) {{
          if (ingestListNote) ingestListNote.textContent = "Ошибка проверки входящих.";
        }} finally {{
          checkInboxBtn.disabled = false;
        }}
      }});
    }}

    if (selectAll && table) {{
      selectAll.addEventListener("change", () => {{
        table.querySelectorAll('input[name="draft_ids"]').forEach((cb) => {{
          cb.checked = selectAll.checked;
        }});
      }});
    }}

    if (deleteForm && table) {{
      deleteForm.addEventListener("submit", (event) => {{
        const selected = Array.from(table.querySelectorAll('input[name="draft_ids"]:checked'));
        if (!selected.length) {{
          event.preventDefault();
          alert("Выберите хотя бы одно входящее письмо.");
          return;
        }}
        if (!confirm(`Удалить выбранные входящие (${{selected.length}} шт.)?`)) {{
          event.preventDefault();
          return;
        }}
        selected.forEach((cb) => {{
          const hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = "draft_ids";
          hidden.value = cb.value;
          deleteForm.appendChild(hidden);
        }});
      }});
    }}

  </script>
</body>
</html>
"""
    return HTMLResponse(html)


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: int) -> dict:
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="draft_not_found")
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()
        return {
            "ok": True,
            "draft": {
                "id": draft.id,
                "status": draft.status,
                "confidence": draft.confidence,
                "parsed_json": draft.parsed_json,
                "offer_payload_json": draft.offer_payload_json,
                "pdf_path": draft.pdf_path,
                "note": draft.note,
            },
            "email": {
                "sender_email": email_row.sender_email if email_row else "",
                "subject": email_row.subject if email_row else "",
                "body_text": email_row.body_text if email_row else "",
            },
        }


@router.get("/ui/{draft_id}", response_class=HTMLResponse)
async def draft_ui(draft_id: int) -> HTMLResponse:
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="draft_not_found")
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()
        already_viewed = (
            session.query(QuoteActionLog.id)
            .filter(QuoteActionLog.draft_id == draft_id, QuoteActionLog.action == "viewed")
            .first()
        )
        if not already_viewed:
            _log_action(session, draft_id, "viewed", "web")
            session.commit()

    parsed_payload = {}
    try:
        parsed_payload = json.loads(draft.parsed_json or "{}")
    except Exception:
        pass
    parsed_payload = _apply_hard_qty_rules(parsed_payload, (email_row.body_text if email_row else "") or "")

    rows_html = ""
    preview_total = 0.0
    for row in (parsed_payload.get("rows") or []) if isinstance(parsed_payload, dict) else []:
        if not isinstance(row, dict):
            continue
        item_name = escape(str(row.get("item_name", "")).strip())
        qty = _parse_num(row.get("qty", 0))
        price = _parse_num(row.get("price", 0))
        if not item_name or qty <= 0:
            continue
        line_total = qty * price
        preview_total += line_total
        rows_html += (
            "<tr>"
            f"<td>{item_name}</td>"
            f"<td>{qty:.2f}</td>"
            f"<td>{_fmt_money(price)}</td>"
            f"<td>{_fmt_money(line_total)}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = '<tr><td colspan="4">Нет распознанных позиций</td></tr>'

    effective_offer = _build_offer_from_draft_payload(parsed_payload)

    vat_mode_map = {
        "cash": "Наличные",
        "without_vat": "Без НДС (+17%)",
        "with_vat": "С НДС (+35%)",
    }
    effective_vat_mode = effective_offer.vat_mode if effective_offer else str(parsed_payload.get("vat_mode", "cash"))
    vat_mode = vat_mode_map.get(effective_vat_mode, "С НДС (+35%)")
    customer_name = escape(str(parsed_payload.get("customer_name", "")).strip() or "-")
    delivery_address = escape(str(parsed_payload.get("delivery_address", "")).strip() or "-")
    template_label = "С реквизитами ГК" if str(parsed_payload.get("template_type", "with_header")) == "with_header" else "Без реквизитов ГК"
    email_text = escape((email_row.body_text if email_row else "") or "").replace("\n", "<br>")
    status_human = escape(_status_label(draft.status or ""))
    status_cls = f"status-{(draft.status or '').strip().replace('_', '-')}"

    html = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=1" />
  <link rel="stylesheet" href="/static/styles.css?v=81" />
  <title>Черновик #{draft.id}</title>
</head>
<body class="review-page review-detail">
  <div class="actions" style="margin-bottom:12px;">
    <a class="btn btn-surface btn-small back" href="/review/ui">Назад к входящим</a>
    <button id="refresh-inbox-btn" class="btn btn-surface btn-small aux" type="button">Входящие</button>
    <p id="refresh-inbox-note" class="ingest-note"></p>
  </div>

  <div class="card meta">
    <div class="meta-label">ID</div><div>{draft.id}</div>
    <div class="meta-label">Статус</div><div><span class="status-chip {status_cls}">{status_human}</span></div>
    <div class="meta-label">Уверенность</div><div>{int((draft.confidence or 0) * 100)}%</div>
    <div class="meta-label">Отправитель</div><div>{escape((email_row.sender_email if email_row else '') or '')}</div>
    <div class="meta-label">Тема</div><div>{escape((email_row.subject if email_row else '') or '')}</div>
  </div>

  <div class="card">
    <h3>Текст письма клиента</h3>
    <div class="text-block">{email_text or 'Пусто'}</div>
  </div>

  <div class="card">
    <h3>Превью PDF (как уйдет клиенту)</h3>
    <div class="pdf-preview-wrap">
      <iframe class="pdf-preview" src="/review/drafts/{draft.id}/preview-pdf"></iframe>
    </div>
  </div>

  <div class="card">
    <h3>Превью коммерческого предложения</h3>
    <div class="text-block">
      <div><strong>Клиент:</strong> {customer_name}</div>
      <div><strong>Форма оплаты:</strong> {vat_mode}</div>
      <div><strong>Шаблон:</strong> {template_label}</div>
      <div><strong>Адрес доставки:</strong> {delivery_address}</div>
      <table class="preview-table">
        <thead>
          <tr><th>Номенклатура</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
      <div class="preview-total">Итого: {_fmt_money(preview_total)} руб.</div>
    </div>
  </div>

  <div class="actions">
    <form id="approve-form" method="post" action="/review/ui/{draft.id}/approve">
      <button id="approve-btn" class="btn btn-small" type="submit">Подтвердить</button>
    </form>
    <form method="post" action="/review/ui/{draft.id}/reject">
      <input type="text" name="reason" placeholder="Причина (опционально)" />
      <button class="btn btn-surface btn-small" type="submit">Отклонить</button>
    </form>
  </div>

  <div id="approve-progress" class="progress-wrap">
    <svg class="progress-ring" viewBox="0 0 28 28" aria-hidden="true">
      <circle class="progress-bg" cx="14" cy="14" r="12"></circle>
      <circle id="approve-progress-fill" class="progress-fill" cx="14" cy="14" r="12"></circle>
    </svg>
    <div id="approve-progress-text" class="progress-text">Запускаю отправку...</div>
  </div>

  <script>
    const approveForm = document.getElementById("approve-form");
    const approveBtn = document.getElementById("approve-btn");
    const progressWrap = document.getElementById("approve-progress");
    const progressFill = document.getElementById("approve-progress-fill");
    const progressText = document.getElementById("approve-progress-text");
    const refreshInboxBtn = document.getElementById("refresh-inbox-btn");
    const refreshInboxNote = document.getElementById("refresh-inbox-note");
    const ringLength = 75.4;
    let pseudoProgress = 0;
    let timerId = null;

    function setApproveProgress(percent, done = false) {{
      const p = Math.max(0, Math.min(100, percent));
      const offset = ringLength * (1 - p / 100);
      progressFill.style.strokeDashoffset = String(offset);
      progressFill.style.stroke = done ? "#2e9e66" : "#3c6ff2";
    }}

    if (approveForm) {{
      approveForm.addEventListener("submit", async (event) => {{
        event.preventDefault();
        if (approveBtn.disabled) return;

        approveBtn.disabled = true;
        progressWrap.style.display = "inline-flex";
        progressText.textContent = "Подготовка КП...";
        pseudoProgress = 8;
        setApproveProgress(pseudoProgress);

        timerId = window.setInterval(() => {{
          pseudoProgress = Math.min(92, pseudoProgress + 7);
          if (pseudoProgress < 45) {{
            progressText.textContent = "Подготовка КП...";
          }} else if (pseudoProgress < 80) {{
            progressText.textContent = "Отправка email...";
          }} else {{
            progressText.textContent = "Завершаю...";
          }}
          setApproveProgress(pseudoProgress);
        }}, 350);

        try {{
          const response = await fetch("/review/drafts/{draft.id}/approve", {{
            method: "POST",
            headers: {{ "Accept": "application/json" }}
          }});
          const data = await response.json().catch(() => ({{}}));
          if (!response.ok || !data.ok) {{
            throw new Error(data.detail || data.reason || "Ошибка отправки");
          }}
          if (timerId) window.clearInterval(timerId);
          setApproveProgress(100, true);
          progressText.textContent = "Готово. КП отправлено.";
          window.setTimeout(() => window.location.reload(), 700);
        }} catch (err) {{
          if (timerId) window.clearInterval(timerId);
          approveBtn.disabled = false;
          progressFill.style.stroke = "#c44444";
          progressText.textContent = "Не удалось отправить. Попробуйте снова.";
        }}
      }});
    }}

    if (refreshInboxBtn) {{
      refreshInboxBtn.addEventListener("click", async () => {{
        refreshInboxBtn.disabled = true;
        if (refreshInboxNote) refreshInboxNote.textContent = "Обновляю почту...";
        try {{
          const response = await fetch("/review/ingest", {{ method: "POST" }});
          const data = await response.json().catch(() => ({{}}));
          if (!response.ok || !data.ok) {{
            throw new Error(data.error || "Не удалось обновить входящие");
          }}
          if (refreshInboxNote) {{
            refreshInboxNote.textContent = data.message || `Забрано новых писем: ${{data.ingested}}.`;
          }}
          if (data.ingested > 0) {{
            window.setTimeout(() => window.location.reload(), 600);
          }}
        }} catch (err) {{
          if (refreshInboxNote) refreshInboxNote.textContent = "Ошибка обновления входящих.";
        }} finally {{
          refreshInboxBtn.disabled = false;
        }}
      }});
    }}
  </script>
</body>
</html>
"""
    return HTMLResponse(html)


def _log_action(session, draft_id: int, action: str, actor: str, details: str = "") -> None:
    session.add(QuoteActionLog(draft_id=draft_id, action=action, actor=actor, details=details))


def _build_offer_from_draft_payload(parsed_payload: dict):
    # Local import to avoid circular imports at module load.
    from main import OfferInput, OfferRow

    rows_payload = parsed_payload.get("rows") if isinstance(parsed_payload, dict) else []
    rows = []
    for row in rows_payload or []:
        if not isinstance(row, dict):
            continue
        item_name = str(row.get("item_name", "")).strip()
        qty = _parse_num(row.get("qty", 0))
        base_price = _parse_num(row.get("price", 0))
        if not item_name or qty <= 0:
            continue
        if base_price <= 0:
            guessed = _guess_cash_price(item_name)
            if guessed:
                base_price = guessed
        rows.append(OfferRow(item_name=item_name, qty=qty, price=max(0.0, base_price)))

    if not rows:
        return None

    from datetime import date

    # Business rule for AI-email flow: always produce "with_vat".
    vat_mode = "with_vat"
    template_type = str(parsed_payload.get("template_type", "with_header"))
    if template_type not in {"with_header", "free"}:
        template_type = "with_header"

    return OfferInput(
        offer_date=date.today(),
        vat_mode=vat_mode,
        template_type=template_type,
        apply_rounding=True,
        include_signature=template_type == "with_header",
        customer_name=str(parsed_payload.get("customer_name", "")).strip(),
        delivery_address=str(parsed_payload.get("delivery_address", "")).strip(),
        rows=rows,
    )


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int) -> dict:
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="draft_not_found")
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()
        recipient = (email_row.sender_email if email_row else "") or ""
        if "@" not in recipient:
            raise HTTPException(status_code=400, detail="invalid_recipient_email")

        try:
            parsed_payload = json.loads(draft.parsed_json or "{}")
        except Exception:
            parsed_payload = {}
        parsed_payload = _apply_hard_qty_rules(parsed_payload, (email_row.body_text if email_row else "") or "")
        offer = _build_offer_from_draft_payload(parsed_payload)
        if offer is None:
            draft.status = "needs_clarification"
            draft.note = "Не удалось собрать позиции КП. Нужны уточнения."
            _log_action(session, draft_id, "approve_failed", "system", "No valid rows in parsed payload")
            session.commit()
            return {"ok": False, "reason": "no_valid_rows"}

        # Local import to avoid circular imports at module import time.
        from main import build_pdf, send_offer_email

        pdf_bytes = build_pdf(offer)
        send_offer_email(recipient_email=recipient, offer=offer, pdf_bytes=pdf_bytes)

        draft.status = "sent"
        draft.offer_payload_json = json.dumps(parsed_payload, ensure_ascii=False)
        draft.note = f"КП отправлено клиенту: {recipient}"
        _log_action(session, draft_id, "approved_and_sent", "user", f"sent_to={recipient}")
        session.commit()
    return {"ok": True, "sent_to": recipient}


@router.get("/drafts/{draft_id}/preview-pdf")
async def preview_draft_pdf(draft_id: int) -> StreamingResponse:
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="draft_not_found")
        email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()
        try:
            parsed_payload = json.loads(draft.parsed_json or "{}")
        except Exception:
            parsed_payload = {}
    parsed_payload = _apply_hard_qty_rules(parsed_payload, (email_row.body_text if email_row else "") or "")

    offer = _build_offer_from_draft_payload(parsed_payload)
    if offer is None:
        raise HTTPException(status_code=400, detail="no_valid_rows_for_pdf_preview")

    from main import build_pdf

    pdf_bytes = build_pdf(offer)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="draft_{draft_id}.pdf"'},
    )


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(draft_id: int, reason: str = "") -> dict:
    with get_session() as session:
        draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="draft_not_found")
        draft.status = "rejected"
        _log_action(session, draft_id, "rejected", "user", reason)
        session.commit()
    return {"ok": True}


@router.post("/ui/{draft_id}/approve")
async def approve_draft_ui(draft_id: int) -> RedirectResponse:
    await approve_draft(draft_id)
    return RedirectResponse(url=f"/review/ui/{draft_id}", status_code=303)


@router.post("/ui/{draft_id}/reject")
async def reject_draft_ui(draft_id: int, reason: str = Form(default="")) -> RedirectResponse:
    await reject_draft(draft_id, reason)
    return RedirectResponse(url=f"/review/ui/{draft_id}", status_code=303)


@router.post("/ui/delete-selected")
async def delete_selected_drafts_ui(draft_ids: list[int] = Form(default=[])) -> RedirectResponse:
    if not draft_ids:
        return RedirectResponse(url="/review/ui", status_code=303)
    ids = sorted(set(int(x) for x in draft_ids if int(x) > 0))
    if not ids:
        return RedirectResponse(url="/review/ui", status_code=303)
    with get_session() as session:
        session.query(QuoteActionLog).filter(QuoteActionLog.draft_id.in_(ids)).delete(synchronize_session=False)
        session.query(QuoteDraft).filter(QuoteDraft.id.in_(ids)).delete(synchronize_session=False)
        session.commit()
    return RedirectResponse(url="/review/ui", status_code=303)
