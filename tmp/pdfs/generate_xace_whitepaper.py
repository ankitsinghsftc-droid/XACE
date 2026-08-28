"""Build the XACE architecture whitepaper as a publication-quality PDF.

The Markdown source is human-readable. This generator converts publication
markers into vector diagrams and derives the 100-task appendix from the
repository tasklist so status text cannot silently drift.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "output" / "pdf" / "Xace_Architecture_and_Platform_Whitepaper.md"
TASKLIST = ROOT / "XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md"
OUTPUT = ROOT / "output" / "pdf" / "Xace_Deterministic_Gameplay_Infrastructure_Whitepaper.pdf"

PAGE_W, PAGE_H = A4
LEFT = 18 * mm
RIGHT = 18 * mm
TOP = 20 * mm
BOTTOM = 18 * mm
CONTENT_W = PAGE_W - LEFT - RIGHT

NAVY = HexColor("#081A2B")
NAVY_2 = HexColor("#102C46")
BLUE = HexColor("#176B87")
CYAN = HexColor("#23B5D3")
TEAL = HexColor("#0A8F8C")
GREEN = HexColor("#2AA876")
AMBER = HexColor("#E6A43A")
RED = HexColor("#D75A4A")
INK = HexColor("#15212B")
MUTED = HexColor("#5C6B78")
PALE = HexColor("#F2F6F8")
PALE_BLUE = HexColor("#EAF4F8")
PALE_GREEN = HexColor("#EAF7F1")
PALE_AMBER = HexColor("#FFF5E2")
GRID = HexColor("#C7D4DB")
WHITE = colors.white


def register_fonts() -> tuple[str, str, str, str, str]:
    """Register Windows publication fonts with built-in fallbacks."""

    candidates = {
        "XaceSans": Path(r"C:\Windows\Fonts\arial.ttf"),
        "XaceSansBold": Path(r"C:\Windows\Fonts\arialbd.ttf"),
        "XaceSansItalic": Path(r"C:\Windows\Fonts\ariali.ttf"),
        "XaceMono": Path(r"C:\Windows\Fonts\consola.ttf"),
        "XaceMonoBold": Path(r"C:\Windows\Fonts\consolab.ttf"),
    }
    fallback = {
        "XaceSans": "Helvetica",
        "XaceSansBold": "Helvetica-Bold",
        "XaceSansItalic": "Helvetica-Oblique",
        "XaceMono": "Courier",
        "XaceMonoBold": "Courier-Bold",
    }
    resolved: dict[str, str] = {}
    for name, path in candidates.items():
        if path.exists():
            pdfmetrics.registerFont(TTFont(name, str(path)))
            resolved[name] = name
        else:
            resolved[name] = fallback[name]
    return (
        resolved["XaceSans"],
        resolved["XaceSansBold"],
        resolved["XaceSansItalic"],
        resolved["XaceMono"],
        resolved["XaceMonoBold"],
    )


SANS, SANS_BOLD, SANS_ITALIC, MONO, MONO_BOLD = register_fonts()


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "WPBody",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=9.15,
            leading=13.1,
            textColor=INK,
            spaceAfter=5.2,
            splitLongWords=True,
            allowWidows=0,
            allowOrphans=0,
        ),
        "lead": ParagraphStyle(
            "WPLead",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=11.2,
            leading=16.2,
            textColor=NAVY_2,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "WPHeading1",
            parent=base["Heading1"],
            fontName=SANS_BOLD,
            fontSize=20.5,
            leading=24,
            textColor=NAVY,
            spaceBefore=0,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "WPHeading2",
            parent=base["Heading2"],
            fontName=SANS_BOLD,
            fontSize=13.4,
            leading=16.4,
            textColor=BLUE,
            spaceBefore=10,
            spaceAfter=5.5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "WPHeading3",
            parent=base["Heading3"],
            fontName=SANS_BOLD,
            fontSize=10.5,
            leading=13.2,
            textColor=NAVY_2,
            spaceBefore=7,
            spaceAfter=3.5,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "WPBullet",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=8.95,
            leading=12.6,
            leftIndent=12,
            firstLineIndent=-7,
            bulletIndent=3,
            textColor=INK,
            spaceAfter=2.8,
            splitLongWords=True,
        ),
        "number": ParagraphStyle(
            "WPNumber",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=8.95,
            leading=12.6,
            leftIndent=15,
            firstLineIndent=-11,
            textColor=INK,
            spaceAfter=2.8,
            splitLongWords=True,
        ),
        "table": ParagraphStyle(
            "WPTable",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=7.35,
            leading=9.4,
            textColor=INK,
            splitLongWords=True,
        ),
        "table_head": ParagraphStyle(
            "WPTableHead",
            parent=base["BodyText"],
            fontName=SANS_BOLD,
            fontSize=7.4,
            leading=9.3,
            textColor=WHITE,
            splitLongWords=True,
        ),
        "code": ParagraphStyle(
            "WPCode",
            parent=base["Code"],
            fontName=MONO,
            fontSize=6.85,
            leading=9.3,
            textColor=HexColor("#DCEAF1"),
            splitLongWords=False,
            wordWrap=None,
        ),
        "caption": ParagraphStyle(
            "WPCaption",
            parent=base["BodyText"],
            fontName=SANS_ITALIC,
            fontSize=7.5,
            leading=9.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "WPSmall",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
        "cover_kicker": ParagraphStyle(
            "CoverKicker",
            parent=base["BodyText"],
            fontName=SANS_BOLD,
            fontSize=9,
            leading=11,
            textColor=CYAN,
            tracking=1.8,
            spaceAfter=8,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName=SANS_BOLD,
            fontSize=43,
            leading=44,
            textColor=WHITE,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=18,
            leading=23,
            textColor=HexColor("#CFE5EE"),
            spaceAfter=18,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=base["BodyText"],
            fontName=SANS,
            fontSize=9.5,
            leading=14,
            textColor=HexColor("#B4C8D2"),
        ),
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=base["Heading1"],
            fontName=SANS_BOLD,
            fontSize=24,
            leading=28,
            textColor=NAVY,
            spaceAfter=12,
        ),
    }


STYLES = make_styles()


def inline_markup(value: str) -> str:
    """Convert the small Markdown inline subset used by the publication."""

    value = html.escape(value.strip(), quote=False)
    value = re.sub(
        r"\x60([^\x60]+)\x60",
        lambda match: (
            f'<font name="{MONO}" color="#0E627A">{match.group(1)}</font>'
        ),
        value,
    )
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    value = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<link href="\2" color="#176B87">\1</link>',
        value,
    )
    return value
