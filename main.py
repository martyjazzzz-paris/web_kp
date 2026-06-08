from __future__ import annotations

import os
import smtplib
import ssl
import logging
import threading
import math
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from fastapi.templating import Jinja2Templates
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from pydantic import BaseModel, Field, field_validator
from db import get_session, init_db
from models import InboundEmail, QuoteActionLog, QuoteDraft
from review_routes import router as review_router
from paths import (
    SIGNATURE_IMAGE_PATH,
    TEMPLATE_BEZ_PATH,
    configure_pdf_font,
    resolve_logo_path,
    resolve_stamp_path,
)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()
SMTP_TIMEOUT_SECONDS = float(os.getenv("SMTP_TIMEOUT_SECONDS", "20"))
SITE_ACCESS_CODE = os.getenv("SITE_ACCESS_CODE", "").strip()


class NoCacheStaticFiles(StarletteStaticFiles):
    """CSS/JS с диска (volume) — без долгого кэша браузера после деплоя."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".css", ".js")):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


def _read_design_version() -> int | None:
    css_path = STATIC_DIR / "styles.css"
    if not css_path.is_file():
        return None
    for line in css_path.read_text(encoding="utf-8").splitlines():
        if "--design-version:" in line:
            try:
                return int(line.split(":", 1)[1].strip().rstrip(";"))
            except ValueError:
                return None
    return None


app = FastAPI(title="KP Generator")
app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
logger = logging.getLogger("kp_mailer")
MAIL_JOBS: dict[str, dict[str, str]] = {}
MAIL_JOBS_LOCK = threading.Lock()
app.include_router(review_router)


@app.get("/health/design")
def health_design() -> JSONResponse:
    css_path = STATIC_DIR / "styles.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    return JSONResponse(
        {
            "design_version": _read_design_version(),
            "has_top_split": ".top-split" in css_text,
            "has_design_mark": "top-split" in css_text,
            "css_bytes": css_path.stat().st_size if css_path.is_file() else 0,
        }
    )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.middleware("http")
async def access_code_guard(request: Request, call_next):
    if not SITE_ACCESS_CODE:
        return await call_next(request)

    path = request.url.path
    allowed_prefixes = ("/static/", "/access")
    if path.startswith(allowed_prefixes):
        return await call_next(request)

    has_access_cookie = request.cookies.get("kp_access_granted") == "1"
    if not has_access_cookie:
        next_url = quote_plus(path)
        return RedirectResponse(url=f"/access?next={next_url}", status_code=303)

    return await call_next(request)


class OfferRow(BaseModel):
    item_name: str = Field(min_length=1)
    qty: float = Field(gt=0)
    price: float = Field(ge=0)

    @field_validator("item_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return v.strip()

    @property
    def amount(self) -> float:
        return round(self.qty * self.price, 2)


class OfferInput(BaseModel):
    offer_date: date
    vat_mode: Literal["cash", "without_vat", "with_vat"]
    template_type: Literal["with_header", "free"]
    apply_rounding: bool = False
    include_signature: bool = False
    customer_name: str = ""
    delivery_address: str = ""
    rows: list[OfferRow]

    @property
    def payment_label(self) -> str:
        if self.vat_mode == "cash":
            return "Наличные"
        if self.vat_mode == "without_vat":
            return "Без НДС"
        return "НДС 22%"

    def markup_rate(self) -> float:
        if self.vat_mode == "cash":
            return 0.0
        if self.vat_mode == "without_vat":
            return 0.17
        return 0.35

    @staticmethod
    def _round_up_to_step(value: float, step: int = 5000) -> float:
        if step <= 0:
            return round(value, 2)
        return float(math.ceil(value / step) * step)

    def _raw_adjusted_price(self, row: OfferRow) -> float:
        raw_price = row.price * (1 + self.markup_rate())
        return round(raw_price, 2)

    def _raw_row_amount(self, row: OfferRow) -> float:
        raw_amount = row.qty * self._raw_adjusted_price(row)
        return round(raw_amount, 2)

    def adjusted_price(self, row: OfferRow) -> float:
        base_price = self._raw_adjusted_price(row)
        if not (self.apply_rounding and self.vat_mode != "cash"):
            return base_price
        rounded_row_amount = self._round_up_to_step(self._raw_row_amount(row), step=1000)
        if row.qty <= 0:
            return base_price
        return round(rounded_row_amount / row.qty, 2)

    def row_amount(self, row: OfferRow) -> float:
        amount = round(row.qty * self.adjusted_price(row), 2)
        return amount

    @property
    def vat_amount(self) -> float:
        return 0.0

    @property
    def total(self) -> float:
        return round(sum(self.row_amount(r) for r in self.rows), 2)

    @property
    def price_caption(self) -> str:
        if self.vat_mode == "without_vat":
            return "Цена руб. без НДС (+17%)"
        if self.vat_mode == "with_vat":
            return "Цена руб. (+35%)"
        return "Цена руб."

    @property
    def total_caption(self) -> str:
        if self.vat_mode == "without_vat":
            return "Стоимость, руб. без НДС"
        if self.vat_mode == "with_vat":
            return "Стоимость, руб. НДС 22%"
        return "Стоимость, руб."

    @property
    def subtotal(self) -> float:
        return round(sum(self._raw_row_amount(r) for r in self.rows), 2)


NOMENCLATURE = [
    "Контейнер 20 футов бу",
    "Контейнер 20 футов, высокий бу (20HC)",
    "Контейнер 20 футов, новый бу (20HC)",
    "Контейнер 20 футов НОВЫЙ",
    "Контейнер 40 футов, стандартный бу",
    "Контейнер 40 футов, стандартный НОВЫЙ",
    "Контейнер 40 футов, высокий бу (40HC)",
    "Контейнер 40 футов, высокий IICL (как новый)",
    "Контейнер 40 футов, высокий НОВЫЙ",
    "Доставка",
    "Разгрузка",
]


def parse_rows(items: list[str], qtys: list[str], prices: list[str]) -> list[OfferRow]:
    def parse_num(value: str) -> float:
        raw = str(value or "").strip().replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        if not raw:
            return 0.0
        try:
            return float(raw)
        except Exception:
            return 0.0

    rows: list[OfferRow] = []
    for item, qty, price in zip(items, qtys, prices):
        if not item.strip():
            continue
        row = OfferRow(item_name=item, qty=parse_num(qty), price=parse_num(price))
        rows.append(row)
    return rows


def add_business_days(start_date: date, days: int) -> date:
    """Add N business days (Mon-Fri), skipping weekends."""
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def validate_email_address(email: str) -> bool:
    email = email.strip()
    return "@" in email and "." in email and " " not in email


def send_offer_email(recipient_email: str, offer: OfferInput, pdf_bytes: bytes) -> None:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError("SMTP не настроен (SMTP_HOST, SMTP_USER, SMTP_PASSWORD в .env)")

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = recipient_email
    message["Subject"] = f"Коммерческое предложение от {offer.offer_date.strftime('%d.%m.%Y')}"
    message.set_content(
        "Добрый день!\n"
        "Во вложении Вы найдете коммерческое предложение по вашему запросу. "
        "Если у вас возникнут дополнительные вопросы, пишите, с радостью ответим.\n"
        "Спасибо!\n\n"
        "С уважением,\n"
        "Александр Игнатов / Best regards, Aleksandr Ignatov\n"
        "Руководитель отдела продаж и маркетинга / head of sales and marketing\n"
        "\"Голдконтейнер\" / Goldcontainer Co./ Gcontainer\n"
        "тел: 8 (499) 553-00-73\n"
        "моб: 8 (931) 706-00-76\n"
        "gcontainer.ru | goldcontainer.ru"
    )
    filename = f"KP_{offer.offer_date.isoformat()}_{datetime.now().strftime('%H%M%S')}.pdf"
    message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        SMTP_HOST, SMTP_PORT, context=context, timeout=SMTP_TIMEOUT_SECONDS
    ) as client:
        client.login(SMTP_USER, SMTP_PASSWORD)
        client.send_message(message)
    logger.info("Email sent via SMTP %s:%s", SMTP_HOST, SMTP_PORT)


def send_offer_email_safe(recipient_email: str, offer: OfferInput, pdf_bytes: bytes) -> None:
    try:
        send_offer_email(recipient_email=recipient_email, offer=offer, pdf_bytes=pdf_bytes)
        _mark_sent_from_generator(recipient_email)
        logger.info("Email sent to %s", recipient_email)
    except Exception:
        logger.exception("Email send failed for %s", recipient_email)


def send_offer_email_job(job_id: str, recipient_email: str, offer: OfferInput, pdf_bytes: bytes) -> None:
    with MAIL_JOBS_LOCK:
        MAIL_JOBS[job_id] = {"status": "sending", "error": ""}
    try:
        send_offer_email(recipient_email=recipient_email, offer=offer, pdf_bytes=pdf_bytes)
        _mark_sent_from_generator(recipient_email)
        with MAIL_JOBS_LOCK:
            MAIL_JOBS[job_id] = {"status": "sent", "error": ""}
    except Exception as exc:
        with MAIL_JOBS_LOCK:
            MAIL_JOBS[job_id] = {"status": "error", "error": str(exc)}
        logger.exception("Email job failed %s for %s", job_id, recipient_email)


def _mark_sent_from_generator(recipient_email: str) -> None:
    recipient = (recipient_email or "").strip().lower()
    if not recipient:
        return
    with get_session() as session:
        pair = (
            session.query(QuoteDraft, InboundEmail)
            .join(InboundEmail, InboundEmail.id == QuoteDraft.inbound_email_id)
            .filter(InboundEmail.sender_email.ilike(recipient))
            .order_by(QuoteDraft.id.desc())
            .first()
        )
        if not pair:
            return
        draft, _ = pair
        action = QuoteActionLog(
            draft_id=draft.id,
            action="generator_sent",
            actor="user",
            details=f"recipient={recipient_email}",
        )
        session.add(action)
        session.commit()


def build_pdf(offer: OfferInput) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    base_font = configure_pdf_font(pdf)
    pdf.set_font(base_font, size=11)

    logo_path = resolve_logo_path()
    has_logo = logo_path is not None
    logo_right_edge = 200.0
    if has_logo:
        # Right-top placement with margins.
        logo_w = 15
        top_margin = 7
        right_margin = 15
        logo_x = 210 - right_margin - logo_w
        logo_right_edge = logo_x + logo_w
        pdf.image(str(logo_path), x=logo_x, y=top_margin, w=logo_w)
        pdf.set_y(top_margin)
    else:
        pdf.set_y(12)

    # Correct mapping: with_header = "С реквизитами", free = "Без реквизитов"
    if offer.template_type == "with_header":
        pdf.set_font(base_font, "B", 14)
        pdf.set_font(base_font, size=10)
        pdf.cell(0, 6, "ООО «Группа компаний Голдконтейнер»", ln=1)
        pdf.cell(0, 6, "107031, город Москва, ул. Рождественка, д. 5/7 стр. 2", ln=1)
        pdf.cell(0, 6, "ИНН 7702838903", ln=1)
        pdf.cell(0, 6, "e-mail: manager@gcontainer.ru / sales@goldcontainer.ru", ln=1)
        pdf.cell(0, 6, "Тел: 8 (499) 553-00-73 | Моб: 8 (931) 706-00-76", ln=1)
        pdf.cell(0, 6, "gcontainer.ru | goldcontainer.ru", ln=1)
        pdf.ln(24)
    else:
        pdf.set_font(base_font, "B", 14)
        pdf.set_font(base_font, size=10)
        pdf.cell(0, 6, "Отдел продаж контейнерных терминалов", ln=1)
        pdf.cell(0, 6, "«ГОЛДКОНТЕЙНЕР»", ln=1)
        pdf.cell(0, 6, "e-mail: manager@gcontainer.ru / sales@goldcontainer.ru", ln=1)
        pdf.cell(0, 6, "Тел: 8 (499) 553-00-73 | Моб: 8 (931) 706-00-76", ln=1)
        pdf.cell(0, 6, "gcontainer.ru | goldcontainer.ru", ln=1)
        pdf.ln(24)

    pdf.set_font(base_font, "B", 17)
    title_text = "Коммерческое предложение"
    title_y = pdf.get_y()
    # Same faux-bold approach as "Итого"
    pdf.cell(0, 9, title_text, ln=0, align="C")
    pdf.set_y(title_y)
    pdf.set_x(pdf.l_margin + 0.25)
    pdf.cell(0, 9, title_text, ln=1, align="C")
    pdf.ln(10)
    pdf.set_font(base_font, size=11)
    pdf.cell(95, 7, f"Дата: {offer.offer_date.strftime('%d.%m.%Y')}")
    city_col_width = logo_right_edge - pdf.get_x()
    pdf.cell(city_col_width, 7, "г. Москва", ln=1, align="R")
    if offer.customer_name.strip():
        pdf.cell(0, 7, f"Клиент: {offer.customer_name.strip()}", ln=1)
    pdf.ln(14)

    pdf.set_font(base_font, "B", 10)
    # Подбираем ширину колонок под реальную длину текста.
    max_name = max([pdf.get_string_width("Наименование")] + [pdf.get_string_width(r.item_name[:40]) for r in offer.rows])
    max_qty = max([pdf.get_string_width("Кол-во")] + [pdf.get_string_width(f"{r.qty:.2f}") for r in offer.rows])
    max_form = max([pdf.get_string_width("Форма"), pdf.get_string_width(offer.payment_label)])
    max_price = max([pdf.get_string_width("Цена руб.")] + [pdf.get_string_width(f"{offer.adjusted_price(r):.2f}") for r in offer.rows])
    max_sum = max([pdf.get_string_width("Стоимость, руб.")] + [pdf.get_string_width(f"{offer.row_amount(r):.2f}") for r in offer.rows])

    col_w = [
        max_name + 8,
        max_qty + 8,
        max_form + 8,
        max_price + 10,
        max_sum + 10,
    ]
    # Keep content-driven widths; only shrink proportionally if table exceeds page width.
    table_total = 190.0
    current_total = sum(col_w)
    if current_total > table_total:
        ratio = table_total / current_total
        col_w = [w * ratio for w in col_w]

    pdf.cell(col_w[0], 8, "Наименование", border=1)
    pdf.cell(col_w[1], 8, "Кол-во", border=1)
    pdf.cell(col_w[2], 8, "Форма", border=1)
    pdf.cell(col_w[3], 8, "Цена руб.", border=1)
    pdf.cell(col_w[4], 8, "Стоимость, руб.", border=1, ln=1)

    pdf.set_font(base_font, size=10)
    for row in offer.rows:
        pdf.cell(col_w[0], 8, row.item_name[:40], border=1)
        pdf.cell(col_w[1], 8, f"{row.qty:.2f}", border=1)
        pdf.cell(col_w[2], 8, offer.payment_label, border=1)
        pdf.cell(col_w[3], 8, f"{offer.adjusted_price(row):.2f}", border=1)
        pdf.cell(col_w[4], 8, f"{offer.row_amount(row):.2f}", border=1, ln=1)

    pdf.ln(4)
    pdf.set_font(base_font, "B", 11)
    pdf.cell(0, 7, f"Форма оплаты: {offer.payment_label}", ln=1)
    pdf.set_font(base_font, "B", 14)
    total_text = f"Итого: {offer.total:.2f} руб."
    # Faux-bold: render twice with tiny horizontal offset, keeping same font size.
    x, y = pdf.get_x(), pdf.get_y()
    pdf.cell(0, 7, total_text, ln=0)
    pdf.set_xy(x + 0.25, y)
    pdf.cell(0, 7, total_text, ln=1)

    if offer.template_type == "with_header":
        pdf.ln(6)
        pdf.set_font(base_font, size=10)
        pdf.cell(0, 6, "Мы гарантируем, что наши контейнеры:", ln=1)
        pdf.cell(0, 6, "- Герметичны (не имеют сквозных отверстий, двери закрываются плотно);", ln=1)
        pdf.cell(0, 6, "- С исправными запорными механизмами;", ln=1)
        pdf.cell(0, 6, "- Имеют оригинальную табличку КБК;", ln=1)
        pdf.cell(0, 6, "- Без нарушений геометрии несущей конструкции;", ln=1)
        pdf.cell(0, 6, "- Пригодны для международных перевозок различным типом транспорта.", ln=1)
        pdf.ln(2)
        pdf.ln(2)
        valid_until = add_business_days(offer.offer_date, 7).strftime("%d.%m.%Y")
        if offer.delivery_address.strip():
            pdf.cell(0, 6, f"Доставка по адресу: {offer.delivery_address.strip()}", ln=1)
        pdf.cell(0, 6, f"Цены действительны до: {valid_until}", ln=1)
    else:
        pdf.ln(6)
        pdf.set_font(base_font, size=10)
        pdf.cell(0, 6, "Мы гарантируем, что наши контейнеры:", ln=1)
        pdf.cell(0, 6, "- Герметичны (не имеют сквозных отверстий, двери закрываются плотно);", ln=1)
        pdf.cell(0, 6, "- С исправными запорными механизмами;", ln=1)
        pdf.cell(0, 6, "- Имеют оригинальную табличку КБК;", ln=1)
        pdf.cell(0, 6, "- Без нарушений геометрии несущей конструкции;", ln=1)
        pdf.cell(0, 6, "- Пригодны для международных перевозок различным типом транспорта.", ln=1)
        pdf.ln(2)
        valid_until = add_business_days(offer.offer_date, 7).strftime("%d.%m.%Y")
        if offer.delivery_address.strip():
            pdf.cell(0, 6, f"Доставка по адресу: {offer.delivery_address.strip()}", ln=1)
        pdf.cell(0, 6, f"Цены действительны до: {valid_until}", ln=1)

    # For "С реквизитами" signature and stamp must always be present.
    if offer.template_type == "with_header":
        pdf.ln(12)
        # Use the regular body text size for signature block captions.
        pdf.set_font(base_font, size=10)
        left_x = pdf.l_margin
        y = pdf.get_y()

        # Left text block, as in the sample.
        pdf.set_xy(left_x + 2, y)
        pdf.cell(78, 7, "Генеральный директор")
        pdf.set_xy(left_x + 2, y + 7)
        pdf.cell(78, 7, 'ООО «Группа компаний Голдконтейнер»')

        # Right signature line + name block.
        sig_line_x = 134
        sig_line_y = y + 3.4
        sig_line_w = 30

        stamp_path = resolve_stamp_path()
        if stamp_path is not None:
            # Draw stamp first so it never covers the signature.
            stamp_w = 60
            stamp_x = sig_line_x + (sig_line_w - stamp_w) / 2 - 12
            stamp_y = y + 4.0
            pdf.image(str(stamp_path), x=stamp_x, y=stamp_y, w=stamp_w)

        # Draw line and signature on top to keep them clearly visible.
        pdf.line(sig_line_x, sig_line_y, sig_line_x + sig_line_w, sig_line_y)
        if SIGNATURE_IMAGE_PATH.exists():
            pdf.image(str(SIGNATURE_IMAGE_PATH), x=sig_line_x - 1.5, y=sig_line_y - 11.6, w=36)

        pdf.set_xy(sig_line_x + sig_line_w + 2, y)
        pdf.cell(28, 7, "Мурзаев Ф.Д.")

    return bytes(pdf.output(dest="S"))


def build_pdf_on_bez_template(offer: OfferInput) -> bytes:
    """Overlay dynamic table values on top of the provided BEZ.pdf blank."""
    if not TEMPLATE_BEZ_PATH.exists():
        return build_pdf(offer)

    # Overlay layer with only dynamic values (no extra table borders).
    overlay = FPDF(orientation="P", unit="mm", format="A4")
    overlay.add_page()
    overlay_family = configure_pdf_font(overlay)
    overlay.set_font(overlay_family, size=9)

    # Date area (under title block in the provided blank).
    overlay.set_xy(16, 45)
    overlay.cell(0, 5, f"Дата: {offer.offer_date.strftime('%d.%m.%Y')}")

    # Table rows area (header and lines are already on the source blank).
    # We only place text inside existing cells.
    y = 73
    row_h = 7
    for row in offer.rows[:10]:
        overlay.set_xy(15, y)
        overlay.cell(86, row_h, row.item_name[:40])
        overlay.set_xy(101, y)
        overlay.cell(16, row_h, f"{row.qty:.2f}", align="C")
        overlay.set_xy(126, y)
        overlay.cell(30, row_h, f"{offer.adjusted_price(row):.2f}", align="R")
        overlay.set_xy(166, y)
        overlay.cell(26, row_h, f"{offer.row_amount(row):.2f}", align="R")
        y += row_h

    overlay.set_xy(15, y + 2)
    overlay.cell(80, 6, f"Форма оплаты: {offer.payment_label}")
    overlay.set_xy(166, y + 2)
    overlay.cell(26, 6, f"{offer.total:.2f}", align="R")

    overlay_bytes = bytes(overlay.output(dest="S"))

    base_reader = PdfReader(str(TEMPLATE_BEZ_PATH))
    overlay_reader = PdfReader(BytesIO(overlay_bytes))
    writer = PdfWriter()

    page = base_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _no_cache_html(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _prefill_from_draft(draft: QuoteDraft | None, email_row: InboundEmail | None) -> dict:
    if not draft:
        return {
            "recipient_email": (email_row.sender_email if email_row else "") or "",
            "customer_name": "",
            "delivery_address": "",
            "rows": [],
        }

    payload: dict = {}
    try:
        payload = json.loads(draft.parsed_json or "{}")
    except Exception:
        payload = {}

    rows: list[dict[str, float | str]] = []
    for row in payload.get("rows", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        item = str(row.get("item_name", "")).strip()
        try:
            qty = float(row.get("qty", 0) or 0)
        except Exception:
            qty = 0.0
        try:
            price = float(row.get("price", 0) or 0)
        except Exception:
            price = 0.0
        if not item or qty <= 0:
            continue
        rows.append({"item_name": item, "qty": qty, "price": max(0.0, price)})

    return {
        "recipient_email": (email_row.sender_email if email_row else "") or "",
        "customer_name": str(payload.get("customer_name", "")).strip() if isinstance(payload, dict) else "",
        "delivery_address": str(payload.get("delivery_address", "")).strip() if isinstance(payload, dict) else "",
        "rows": rows,
    }


@app.get("/api/nomenclature")
async def api_nomenclature() -> JSONResponse:
    """Диагностика: какой список реально отдаёт этот процесс сервера."""
    return JSONResponse(
        {"items": NOMENCLATURE, "count": len(NOMENCLATURE)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, draft_id: int | None = None) -> HTMLResponse:
    mail_status = request.query_params.get("mail_status")
    mail_error = request.query_params.get("mail_error")
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_buckets: list[tuple[int, int]] = []
    y, m = now.year, now.month
    for _ in range(6):
        month_buckets.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_buckets.reverse()

    prefill = {"recipient_email": "", "customer_name": "", "delivery_address": "", "rows": []}
    with get_session() as session:
        draft_rows = (
            session.query(QuoteDraft.id, QuoteDraft.status, QuoteDraft.created_at)
            .filter(QuoteDraft.created_at >= today_start)
            .all()
        )
        incoming_total = sum(
            1
            for _, status, _ in draft_rows
            if (status or "").strip() not in {"sent", "rejected"}
        )
        draft_ids = [int(draft_id) for draft_id, _, _ in draft_rows]
        logs: list[tuple[int, str, datetime]] = []
        if draft_ids:
            logs = (
                session.query(QuoteActionLog.draft_id, QuoteActionLog.action, QuoteActionLog.created_at)
                .filter(
                    QuoteActionLog.draft_id.in_(draft_ids),
                    QuoteActionLog.action.in_(["approved_and_sent", "generator_sent"]),
                )
                .all()
            )
        if draft_id and draft_id > 0:
            draft = session.query(QuoteDraft).filter(QuoteDraft.id == draft_id).first()
            email_row = None
            if draft:
                email_row = session.query(InboundEmail).filter(InboundEmail.id == draft.inbound_email_id).first()
            prefill = _prefill_from_draft(draft, email_row)

    sent_ids: set[int] = {int(draft_id) for draft_id, status, _ in draft_rows if status == "sent"}
    generated_ids: set[int] = set()
    for draft_id, action, _ in logs:
        if action in {"approved_and_sent", "generator_sent"}:
            sent_ids.add(int(draft_id))
        if action == "generator_sent":
            generated_ids.add(int(draft_id))

    sent_total = len(sent_ids)
    sent_month = sent_total
    generated_total = len(generated_ids)

    sent_by_month: dict[tuple[int, int], int] = defaultdict(int)
    generated_by_month: dict[tuple[int, int], int] = defaultdict(int)
    counted_sent_drafts: set[int] = set()
    counted_generated_drafts: set[int] = set()
    for draft_id, action, created_at in logs:
        if not created_at or created_at < today_start:
            continue
        key = (created_at.year, created_at.month)
        if key not in month_buckets:
            continue
        draft_key = int(draft_id)
        if action in {"approved_and_sent", "generator_sent"} and draft_key not in counted_sent_drafts:
            sent_by_month[key] += 1
            counted_sent_drafts.add(draft_key)
        if action == "generator_sent" and draft_key not in counted_generated_drafts:
            generated_by_month[key] += 1
            counted_generated_drafts.add(draft_key)

    for draft_id, status, created_at in draft_rows:
        if status != "sent" or int(draft_id) in counted_sent_drafts or not created_at:
            continue
        key = (created_at.year, created_at.month)
        if key in month_buckets:
            sent_by_month[key] += 1

    sent_points_raw: list[dict[str, int | str]] = []
    generated_points_raw: list[dict[str, int | str]] = []
    for bucket_year, bucket_month in month_buckets:
        label = f"{bucket_month}/{str(bucket_year)[-2:]}"
        sent_val = int(sent_by_month.get((bucket_year, bucket_month), 0))
        gen_val = int(generated_by_month.get((bucket_year, bucket_month), 0))
        sent_points_raw.append({"label": label, "value": sent_val})
        generated_points_raw.append({"label": label, "value": gen_val})

    sent_max = max([int(p["value"]) for p in sent_points_raw] + [1])
    gen_max = max([int(p["value"]) for p in generated_points_raw] + [1])
    sent_points = [
        {"label": p["label"], "value": p["value"], "height": max(6, int(int(p["value"]) * 100 / sent_max))}
        for p in sent_points_raw
    ]
    generated_points = [
        {"label": p["label"], "value": p["value"], "height": max(6, int(int(p["value"]) * 100 / gen_max))}
        for p in generated_points_raw
    ]

    context = {
        "request": request,
        "today": date.today().isoformat(),
        "nomenclature": NOMENCLATURE,
        "preview": None,
        "mail_status": mail_status,
        "mail_error": mail_error,
        "kpi_incoming_total": incoming_total,
        "kpi_sent_month": sent_month,
        "kpi_sent_total": sent_total,
        "kpi_generated_total": generated_total,
        "kpi_sent_points": sent_points,
        "kpi_generated_points": generated_points,
        "prefill": prefill,
        "prefill_draft_id": draft_id if draft_id and draft_id > 0 else None,
        "preview_recipient_email": prefill.get("recipient_email", ""),
    }
    return _no_cache_html(templates.TemplateResponse(request, "index.html", context))


@app.get("/access", response_class=HTMLResponse)
async def access_page(request: Request, next: str = "/") -> HTMLResponse:
    html = f"""
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=1" />
    <link rel="stylesheet" href="/static/styles.css?v=82" />
    <title>Доступ к сервису</title>
  </head>
  <body class="access-gate">
    <form class="access-gate__card" method="post" action="/access">
      <img src="/static/favicon.svg" alt="" width="48" height="48" class="access-gate__logo" />
      <h1>Код доступа</h1>
      <p>Введите код, чтобы открыть генератор КП.</p>
      {"<div class='access-gate__err'>Неверный код. Попробуйте еще раз.</div>" if request.query_params.get("error") else ""}
      <label class="access-gate__field">
        <span>Код</span>
        <input type="password" name="code" placeholder="••••" required autofocus />
      </label>
      <input type="hidden" name="next" value="{next}" />
      <button class="btn" type="submit">Войти</button>
    </form>
  </body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/access")
async def access_submit(code: str = Form(...), next: str = Form(default="/")) -> RedirectResponse:
    target = next if next.startswith("/") else "/"
    if code.strip() != SITE_ACCESS_CODE:
        return RedirectResponse(url=f"/access?error=1&next={quote_plus(target)}", status_code=303)

    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie("kp_access_granted", "1", httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return response


@app.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
    apply_rounding: str | None = Form(default=None),
    include_signature: str | None = Form(default=None),
    customer_name: str = Form(default=""),
    delivery_address: str = Form(default=""),
    recipient_email: str = Form(default=""),
    item_name: list[str] = Form(...),
    qty: list[str] = Form(...),
    price: list[str] = Form(...),
) -> HTMLResponse:
    rows = parse_rows(item_name, qty, price)
    offer = OfferInput(
        offer_date=datetime.strptime(offer_date, "%Y-%m-%d").date(),
        vat_mode=vat_mode,
        template_type=template_type,
        apply_rounding=bool(apply_rounding),
        include_signature=bool(include_signature) and template_type == "with_header",
        customer_name=customer_name,
        delivery_address=delivery_address,
        rows=rows,
    )
    context = {
        "request": request,
        "today": offer_date,
        "nomenclature": NOMENCLATURE,
        "preview": offer,
        "mail_status": None,
        "mail_error": None,
        "prefill": {"recipient_email": "", "customer_name": customer_name, "delivery_address": delivery_address, "rows": []},
        "prefill_draft_id": None,
        "preview_recipient_email": recipient_email.strip(),
    }
    return _no_cache_html(templates.TemplateResponse(request, "index.html", context))


@app.post("/generate-pdf")
async def generate_pdf(
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
    apply_rounding: str | None = Form(default=None),
    include_signature: str | None = Form(default=None),
    customer_name: str = Form(default=""),
    delivery_address: str = Form(default=""),
    item_name: list[str] = Form(...),
    qty: list[str] = Form(...),
    price: list[str] = Form(...),
) -> StreamingResponse:
    rows = parse_rows(item_name, qty, price)
    offer = OfferInput(
        offer_date=datetime.strptime(offer_date, "%Y-%m-%d").date(),
        vat_mode=vat_mode,
        template_type=template_type,
        apply_rounding=bool(apply_rounding),
        include_signature=bool(include_signature) and template_type == "with_header",
        customer_name=customer_name,
        delivery_address=delivery_address,
        rows=rows,
    )
    pdf_bytes = build_pdf(offer)
    filename = f"KP_{offer.offer_date.isoformat()}_{datetime.now().strftime('%H%M%S')}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/send-email")
async def send_email(
    background_tasks: BackgroundTasks,
    recipient_email: str = Form(...),
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
    apply_rounding: str | None = Form(default=None),
    include_signature: str | None = Form(default=None),
    customer_name: str = Form(default=""),
    delivery_address: str = Form(default=""),
    item_name: list[str] = Form(...),
    qty: list[str] = Form(...),
    price: list[str] = Form(...),
) -> RedirectResponse:
    recipient_email = recipient_email.strip()
    if not validate_email_address(recipient_email):
        err = quote_plus("Некорректный email получателя.")
        return RedirectResponse(url=f"/?mail_status=error&mail_error={err}", status_code=303)

    rows = parse_rows(item_name, qty, price)
    offer = OfferInput(
        offer_date=datetime.strptime(offer_date, "%Y-%m-%d").date(),
        vat_mode=vat_mode,
        template_type=template_type,
        apply_rounding=bool(apply_rounding),
        include_signature=bool(include_signature) and template_type == "with_header",
        customer_name=customer_name,
        delivery_address=delivery_address,
        rows=rows,
    )
    pdf_bytes = build_pdf(offer)
    try:
        send_offer_email(recipient_email=recipient_email, offer=offer, pdf_bytes=pdf_bytes)
        _mark_sent_from_generator(recipient_email)
        return RedirectResponse(url="/?mail_status=ok", status_code=303)
    except Exception as exc:
        logger.exception("Email send failed for %s", recipient_email)
        err = quote_plus(str(exc))
        return RedirectResponse(url=f"/?mail_status=error&mail_error={err}", status_code=303)


@app.post("/send-email-async")
async def send_email_async(
    background_tasks: BackgroundTasks,
    recipient_email: str = Form(...),
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
    apply_rounding: str | None = Form(default=None),
    include_signature: str | None = Form(default=None),
    customer_name: str = Form(default=""),
    delivery_address: str = Form(default=""),
    item_name: list[str] = Form(...),
    qty: list[str] = Form(...),
    price: list[str] = Form(...),
) -> JSONResponse:
    recipient_email = recipient_email.strip()
    if not validate_email_address(recipient_email):
        return JSONResponse({"ok": False, "error": "Некорректный email получателя."}, status_code=400)

    rows = parse_rows(item_name, qty, price)
    offer = OfferInput(
        offer_date=datetime.strptime(offer_date, "%Y-%m-%d").date(),
        vat_mode=vat_mode,
        template_type=template_type,
        apply_rounding=bool(apply_rounding),
        include_signature=bool(include_signature) and template_type == "with_header",
        customer_name=customer_name,
        delivery_address=delivery_address,
        rows=rows,
    )
    pdf_bytes = build_pdf(offer)
    job_id = uuid4().hex
    with MAIL_JOBS_LOCK:
        MAIL_JOBS[job_id] = {"status": "queued", "error": ""}
    background_tasks.add_task(send_offer_email_job, job_id, recipient_email, offer, pdf_bytes)
    return JSONResponse({"ok": True, "job_id": job_id})


@app.get("/api/email-status/{job_id}")
async def email_status(job_id: str) -> JSONResponse:
    with MAIL_JOBS_LOCK:
        job = MAIL_JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "error": "job_not_found"}, status_code=404)
    return JSONResponse({"ok": True, "status": job["status"], "error": job["error"]})
