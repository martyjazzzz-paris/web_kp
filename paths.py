"""Cross-platform paths for KP assets, fonts, and images."""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

WEB_KP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_KP_DIR.parent
STATIC_DIR = WEB_KP_DIR / "static"
ASSETS_DIR = WEB_KP_DIR / "assets"
FONTS_DIR = STATIC_DIR / "fonts"

LOGO_PATH = STATIC_DIR / "logo.png"
SIGNATURE_IMAGE_PATH = STATIC_DIR / "signature.png"
STAMP_IMAGE_PATH = STATIC_DIR / "stamp.png"
ROBOTO_REGULAR_PATH = FONTS_DIR / "Roboto-Regular.ttf"
ROBOTO_BOLD_PATH = FONTS_DIR / "Roboto-Bold.ttf"


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)


TEMPLATE_BEZ_PATH = _path_from_env("KP_TEMPLATE_BEZ_PATH", ASSETS_DIR / "BEZ.pdf")


def _extra_paths_from_env(name: str) -> list[Path]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [Path(part.strip()).expanduser() for part in raw.split(os.pathsep) if part.strip()]


FALLBACK_LOGO_PATHS = _extra_paths_from_env("KP_LOGO_FALLBACK_PATHS")
FALLBACK_STAMP_PATHS = _extra_paths_from_env("KP_STAMP_FALLBACK_PATHS")


def _system_font_candidates() -> list[tuple[Path, Path]]:
    system = platform.system()
    if system == "Darwin":
        return [
            (
                Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ),
            (
                Path("/Library/Fonts/Arial.ttf"),
                Path("/Library/Fonts/Arial Bold.ttf"),
            ),
        ]
    if system == "Windows":
        win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return [
            (win / "arial.ttf", win / "arialbd.ttf"),
        ]
    return [
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ),
    ]


def resolve_unicode_font_paths() -> tuple[Path | None, Path | None]:
    if ROBOTO_REGULAR_PATH.exists() and ROBOTO_BOLD_PATH.exists():
        return ROBOTO_REGULAR_PATH, ROBOTO_BOLD_PATH
    for regular, bold in _system_font_candidates():
        if regular.exists() and bold.exists():
            return regular, bold
    return None, None


def configure_pdf_font(pdf: FPDF, *, family: str = "AppFont") -> str:
    """Register a Unicode TTF font when available."""
    regular, bold = resolve_unicode_font_paths()
    if regular and bold:
        pdf.add_font(family, "", str(regular))
        pdf.add_font(family, "B", str(bold))
        return family

    logger.warning(
        "Unicode fonts not found. Place Roboto in %s or set KP_* font paths.",
        FONTS_DIR,
    )
    return "Helvetica"


def resolve_logo_path() -> Path | None:
    if LOGO_PATH.exists():
        return LOGO_PATH
    for path in FALLBACK_LOGO_PATHS:
        if path.exists():
            return path
    return None


def resolve_stamp_path() -> Path | None:
    if STAMP_IMAGE_PATH.exists():
        return STAMP_IMAGE_PATH
    for candidate in FALLBACK_STAMP_PATHS:
        if candidate.exists():
            return candidate
    return None
