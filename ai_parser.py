from __future__ import annotations

from bootstrap_env import load_project_env

load_project_env()

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import OpenAI


@dataclass
class ParsedResult:
    payload: dict
    confidence: float
    note: str = ""


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "parse_email.txt"


def _llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai").strip().lower()


def _openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()


def _yandex_api_key() -> str:
    return os.getenv("YANDEX_API_KEY", "").strip()


def _yandex_folder_id() -> str:
    return os.getenv("YANDEX_FOLDER_ID", "").strip()


def _yandex_model() -> str:
    return os.getenv("YANDEX_MODEL", "yandexgpt-lite").strip()


def _yandex_api_url() -> str:
    return os.getenv(
        "YANDEX_API_URL",
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
    ).strip()


def _yandex_retry_attempts() -> int:
    return int(os.getenv("YANDEX_RETRY_ATTEMPTS", "3"))


def _yandex_retry_base_delay() -> float:
    return float(os.getenv("YANDEX_RETRY_BASE_DELAY", "0.8"))

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


def _parse_num(value: object) -> float:
    raw = str(value or "").strip().replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _normalize_payload(payload: dict) -> dict:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_name = str(row.get("item_name", "")).strip()
        if not item_name:
            continue
        qty = _parse_num(row.get("qty", 0))
        price = _parse_num(row.get("price", 0))
        if qty <= 0:
            continue
        normalized_rows.append({"item_name": item_name, "qty": qty, "price": max(0.0, price)})

    # Business rule for email AI flow:
    # inbound requests are always prepared as "with_vat".
    vat_mode = "with_vat"
    template_type = str(payload.get("template_type", "with_header")).strip()
    if template_type not in {"with_header", "free"}:
        template_type = "with_header"

    return {
        "customer_name": str(payload.get("customer_name", "")).strip(),
        "delivery_address": str(payload.get("delivery_address", "")).strip(),
        "vat_mode": vat_mode,
        "template_type": template_type,
        "rows": normalized_rows,
    }


def _guess_cash_price(item_name: str) -> float | None:
    key = (item_name or "").strip().lower().replace("ё", "е")
    if key in CASH_PRICE_BY_NOMENCLATURE:
        return CASH_PRICE_BY_NOMENCLATURE[key]

    # Heuristic fallback by keywords to catch slightly different LLM wording.
    if "контейнер" not in key:
        return None
    if "20" in key:
        if "нов" in key and "бу" not in key:
            return 175000.0
        if "высок" in key and "бу" in key and "нов" in key:
            return 125000.0
        if "высок" in key and "бу" in key:
            return 75000.0
        if "бу" in key:
            return 55000.0
    if "40" in key:
        if "iicl" in key:
            return 125000.0
        if "высок" in key and "нов" in key and "бу" not in key:
            return 170000.0
        if "стандарт" in key and "нов" in key:
            return 140000.0
        if "высок" in key and "бу" in key:
            return 80000.0
        if "стандарт" in key and "бу" in key:
            return 85000.0
    return None


def _extract_requested_container_qty(text: str) -> int | None:
    source = (text or "").lower().replace(",", ".")
    # Patterns like: "2 контейнера", "3 шт контейнеров", "кол-во 5"
    patterns = [
        r"(\d+)\s*(?:шт\.?|штук)?\s*контейнер(?:а|ов)?",
        r"контейнер(?:а|ов)?\s*[-:xх*]?\s*(\d+)",
        r"(?:кол-?во|количество)\s*[:\-]?\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if value > 0:
            return value
    return None


def _extract_container_type_hint(text: str) -> str | None:
    source = (text or "").lower().replace("ё", "е")
    if re.search(r"(20\s*(?:фут|ф|ft))|двадцати?фут", source):
        return "20"
    if re.search(r"(40\s*(?:фут|ф|ft))|сорока?фут", source):
        return "40"
    return None


def _extract_need_qty_hint(text: str) -> int | None:
    source = (text or "").lower()
    # Strong pattern for phrases like: "нужно 10", "требуется 7", "надо 5"
    match = re.search(r"(?:нужно|надо|требуется|необходимо)\s*(\d+)", source, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value > 0 else None


def _extract_qty_near_size_hint(text: str, size_hint: str) -> int | None:
    source = (text or "").lower().replace("ё", "е")
    if size_hint not in {"20", "40"}:
        return None
    # Examples:
    # "на 2 20 футов бу", "нужно 3 шт 40 футов", "2 контейнера 20 футов"
    patterns = [
        rf"(?:на|нужно|надо|требуется|необходимо)?\s*(\d+)\s*(?:шт\.?|штук|контейнер(?:а|ов)?)?\s*{size_hint}\s*(?:фут|ф|ft)",
        rf"(\d+)\s*(?:шт\.?|штук|контейнер(?:а|ов)?)\s*{size_hint}\s*(?:фут|ф|ft)",
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


def _apply_post_rules(normalized_payload: dict, subject: str, body_text: str) -> dict:
    payload = dict(normalized_payload)
    rows = list(payload.get("rows") or [])
    raw_text = f"{subject}\n{body_text}"
    requested_qty = _extract_requested_container_qty(raw_text)
    if requested_qty and rows:
        # If model returned exactly one container row with qty=1, but mail clearly asks >1.
        container_rows = [r for r in rows if "контейнер" in str(r.get("item_name", "")).lower()]
        if len(container_rows) == 1:
            current_qty = float(container_rows[0].get("qty", 0) or 0)
            if current_qty <= 1 and requested_qty > 1:
                container_rows[0]["qty"] = float(requested_qty)

    # Extra strong rule: if mail explicitly says type (20/40) + "нужно N",
    # force qty for that type to N even when LLM guessed 1.
    type_hint = _extract_container_type_hint(raw_text)
    need_qty = _extract_need_qty_hint(raw_text)
    if type_hint and need_qty and rows:
        for row in rows:
            item = str(row.get("item_name", "")).lower()
            if "контейнер" not in item:
                continue
            if type_hint == "20" and "20" in item:
                row["qty"] = float(need_qty)
            elif type_hint == "40" and "40" in item:
                row["qty"] = float(need_qty)

    # Handle phrases like "на 2 20 футов бу".
    qty_near_size = _extract_qty_near_size_hint(raw_text, type_hint or "")
    if type_hint and qty_near_size and rows:
        for row in rows:
            item = str(row.get("item_name", "")).lower()
            if "контейнер" not in item:
                continue
            if type_hint == "20" and "20" in item:
                row["qty"] = float(qty_near_size)
            elif type_hint == "40" and "40" in item:
                row["qty"] = float(qty_near_size)

    # Apply cash base prices for container rows when LLM did not provide price.
    # Delivery/handling stay untouched by business request.
    for row in rows:
        try:
            current_price = float(row.get("price", 0) or 0)
        except Exception:
            current_price = 0
        if current_price > 0:
            continue
        suggested = _guess_cash_price(str(row.get("item_name", "")))
        if suggested:
            row["price"] = float(suggested)
    payload["rows"] = rows
    return payload


def _extract_json_block(text: str) -> dict:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Empty LLM response")

    # Typical case: pure JSON.
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Remove fenced code blocks if present.
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

    # Fallback: take text between first '{' and last '}'.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = cleaned[start : end + 1]
        parsed = json.loads(snippet)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("No JSON object found in LLM response")


def _fallback_parse(subject: str, body_text: str) -> ParsedResult:
    text = f"{subject}\n{body_text}".lower()
    rows = []
    requested_qty = _extract_requested_container_qty(text) or 1
    if "40" in text:
        rows.append({"item_name": "Контейнер 40 футов, стандартный бу", "qty": requested_qty, "price": 0})
    elif "20" in text:
        rows.append({"item_name": "Контейнер 20 футов бу", "qty": requested_qty, "price": 0})

    payload = {
        "customer_name": "",
        "delivery_address": "",
        "vat_mode": "with_vat",
        "template_type": "with_header",
        "rows": rows,
    }
    payload = _apply_post_rules(payload, subject, body_text)
    confidence = 0.65 if rows else 0.15
    note = "Fallback parser used."
    return ParsedResult(payload=payload, confidence=confidence, note=note)


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Извлеки из письма поля customer_name, delivery_address, vat_mode, template_type, rows[]. "
        "Верни только JSON без пояснений."
    )


def _openai_parse(subject: str, body_text: str) -> ParsedResult:
    openai_api_key = _openai_api_key()
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    client = OpenAI(api_key=openai_api_key)
    prompt = _load_prompt()
    user_text = f"Тема:\n{subject}\n\nТекст письма:\n{body_text}\n"

    response = client.chat.completions.create(
        model=_openai_model(),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_text},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    payload = _apply_post_rules(_normalize_payload(parsed), subject, body_text)

    rows = payload["rows"]
    confidence = 0.9 if rows else 0.35
    note = f"LLM parsed via {_openai_model()}"
    return ParsedResult(payload=payload, confidence=confidence, note=note)


def _yandex_parse(subject: str, body_text: str) -> ParsedResult:
    yandex_api_key = _yandex_api_key()
    yandex_folder_id = _yandex_folder_id()
    if not yandex_api_key:
        raise RuntimeError("YANDEX_API_KEY is missing")
    if not yandex_folder_id:
        raise RuntimeError("YANDEX_FOLDER_ID is missing")

    prompt = _load_prompt()
    user_text = f"Тема:\n{subject}\n\nТекст письма:\n{body_text}\n"
    model_uri = f"gpt://{yandex_folder_id}/{_yandex_model()}/latest"
    payload = {
        "modelUri": model_uri,
        "completionOptions": {
            "stream": False,
            "temperature": 0,
            "maxTokens": "2000",
        },
        "messages": [
            {"role": "system", "text": prompt},
            {"role": "user", "text": user_text},
        ],
    }
    headers = {"Authorization": f"Api-Key {yandex_api_key}"}
    last_error: Exception | None = None
    data: dict | None = None

    with httpx.Client(timeout=30) as client:
        for attempt in range(1, max(1, _yandex_retry_attempts()) + 1):
            try:
                response = client.post(_yandex_api_url(), json=payload, headers=headers)
                raw_text = (response.text or "").strip()
                content_type = (response.headers.get("content-type") or "").lower()

                if not raw_text:
                    raise ValueError("Empty response from Yandex API")
                if raw_text.startswith("<"):
                    raise ValueError(f"Yandex returned HTML instead of JSON (status={response.status_code})")
                if "json" not in content_type and not raw_text.startswith("{"):
                    raise ValueError(
                        f"Unexpected content-type from Yandex: {content_type or 'unknown'} "
                        f"(status={response.status_code})"
                    )
                if response.status_code >= 400:
                    raise ValueError(f"Yandex HTTP {response.status_code}: {raw_text[:300]}")

                try:
                    parsed_data = response.json()
                except Exception as exc:
                    raise ValueError(f"Invalid JSON body from Yandex: {raw_text[:300]}") from exc

                if not isinstance(parsed_data, dict):
                    raise ValueError("Yandex JSON body is not an object")
                data = parsed_data
                break
            except Exception as exc:
                last_error = exc
                if attempt >= max(1, _yandex_retry_attempts()):
                    raise
                time.sleep(_yandex_retry_base_delay() * (2 ** (attempt - 1)))

    if data is None:
        raise RuntimeError(f"Yandex response parse failed: {last_error}")

    text = (
        data.get("result", {})
        .get("alternatives", [{}])[0]
        .get("message", {})
        .get("text", "{}")
    )
    parsed = _extract_json_block(text)
    normalized = _apply_post_rules(_normalize_payload(parsed), subject, body_text)
    rows = normalized["rows"]
    confidence = 0.9 if rows else 0.35
    note = f"LLM parsed via yandex:{_yandex_model()}"
    return ParsedResult(payload=normalized, confidence=confidence, note=note)


def parse_inbound_email(subject: str, body_text: str) -> ParsedResult:
    provider = _llm_provider()
    if provider == "openai":
        try:
            return _openai_parse(subject, body_text)
        except Exception:
            fallback = _fallback_parse(subject, body_text)
            fallback.note = "OpenAI parse failed; fallback parser used."
            return fallback
    if provider == "yandex":
        try:
            return _yandex_parse(subject, body_text)
        except Exception as exc:
            fallback = _fallback_parse(subject, body_text)
            fallback.note = f"Yandex parse failed: {exc}; fallback parser used."
            return fallback
    return _fallback_parse(subject, body_text)
