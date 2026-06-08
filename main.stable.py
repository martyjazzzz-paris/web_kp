from __future__ import annotations

from bootstrap_env import load_project_env

load_project_env()

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from pydantic import BaseModel, Field, field_validator

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

app = FastAPI(title="KP Generator")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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

    def adjusted_price(self, row: OfferRow) -> float:
        return round(row.price * (1 + self.markup_rate()), 2)

    def row_amount(self, row: OfferRow) -> float:
        return round(row.qty * self.adjusted_price(row), 2)

    @property
    def vat_amount(self) -> float:
        return 0.0

    @property
    def total(self) -> float:
        return self.subtotal

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
        return round(sum(self.row_amount(r) for r in self.rows), 2)


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
    rows: list[OfferRow] = []
    for item, qty, price in zip(items, qtys, prices):
        if not item.strip():
            continue
        row = OfferRow(item_name=item, qty=float(qty), price=float(price))
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
        pdf.cell(0, 6, "142324, МО, г. Чехов, д. Люторецкая, терр. промзона Люторецкое, д. 4, к. 6, пом. 43", ln=1)
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


@app.get("/api/nomenclature")
async def api_nomenclature() -> JSONResponse:
    """Диагностика: какой список реально отдаёт этот процесс сервера."""
    return JSONResponse(
        {"items": NOMENCLATURE, "count": len(NOMENCLATURE)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    context = {
        "request": request,
        "today": date.today().isoformat(),
        "nomenclature": NOMENCLATURE,
        "preview": None,
    }
    return _no_cache_html(templates.TemplateResponse(request, "index.html", context))


@app.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
    include_signature: str | None = Form(default=None),
    customer_name: str = Form(default=""),
    delivery_address: str = Form(default=""),
    item_name: list[str] = Form(...),
    qty: list[str] = Form(...),
    price: list[str] = Form(...),
) -> HTMLResponse:
    rows = parse_rows(item_name, qty, price)
    offer = OfferInput(
        offer_date=datetime.strptime(offer_date, "%Y-%m-%d").date(),
        vat_mode=vat_mode,
        template_type=template_type,
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
    }
    return _no_cache_html(templates.TemplateResponse(request, "index.html", context))


@app.post("/generate-pdf")
async def generate_pdf(
    offer_date: str = Form(...),
    vat_mode: str = Form(...),
    template_type: str = Form(...),
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
