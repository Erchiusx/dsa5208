"""Render the project README.md as a paginated PDF.

Run from project3/: python3 report/export_readme.py
Requires reportlab. The Markdown source remains the authoritative README.
"""

from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "README.md"
OUTPUT = ROOT / "report" / "README.pdf"
URL = "https://github.com/Erchiusx/dsa5208"

pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuMono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

styles = getSampleStyleSheet()
body = ParagraphStyle("ReadmeBody", parent=styles["BodyText"], fontName="DejaVu",
                      fontSize=8.8, leading=13.0, spaceAfter=6, textColor=colors.HexColor("#202a35"))
title = ParagraphStyle("ReadmeTitle", parent=body, fontName="DejaVu-Bold", fontSize=17,
                       leading=21, spaceBefore=0, spaceAfter=13)
h2 = ParagraphStyle("ReadmeH2", parent=body, fontName="DejaVu-Bold", fontSize=12,
                    leading=16, spaceBefore=15, spaceAfter=7, keepWithNext=True)
h3 = ParagraphStyle("ReadmeH3", parent=body, fontName="DejaVu-Bold", fontSize=10,
                    leading=14, spaceBefore=11, spaceAfter=5, keepWithNext=True)
bullet = ParagraphStyle("ReadmeBullet", parent=body, leftIndent=14, firstLineIndent=-9,
                        spaceAfter=3)
code_style = ParagraphStyle("ReadmeCode", parent=body, fontName="DejaVuMono",
                            fontSize=7.2, leading=10, leftIndent=8, rightIndent=6,
                            backColor=colors.HexColor("#f2f5f8"), borderPadding=7,
                            spaceBefore=4, spaceAfter=9)
def inline(text: str) -> str:
    """Handle README links, inline code and bold without changing their text."""
    tokens: list[str] = []

    def hold(value: str) -> str:
        tokens.append(value)
        return f"@@TOKEN{len(tokens) - 1}@@"

    text = re.sub(r"\[([^]]+)\]\(([^)]+)\)",
                  lambda m: hold(f'<link href="{html.escape(m[2], quote=True)}" color="#135a7a">'
                                 f'{html.escape(m[1])}</link>'), text)
    text = re.sub(r"`([^`]+)`", lambda m: hold(f'<font name="DejaVuMono">{html.escape(m[1])}</font>'), text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    for index, value in enumerate(tokens):
        text = text.replace(f"@@TOKEN{index}@@", value)
    return text


def page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("DejaVu", 7)
    canvas.setFillColor(colors.HexColor("#66717c"))
    canvas.drawString(42, 25, "DSA5208 Project 3 — README")
    canvas.drawRightString(A4[0] - 42, 25, str(doc.page))
    canvas.restoreState()


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    paragraph: list[str] = []
    code: list[str] | None = None

    def flush_paragraph() -> None:
        if paragraph:
            story.append(Paragraph(inline(" ".join(part.strip() for part in paragraph)), body))
            paragraph.clear()

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            if code is None:
                code = []
            else:
                wrapped = []
                for item in code:
                    wrapped.extend(textwrap.wrap(item, width=96, break_long_words=True,
                                                break_on_hyphens=False, replace_whitespace=False,
                                                drop_whitespace=False) or [""])
                story.append(Preformatted("\n".join(wrapped), code_style, splitChars=" "))
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            style = {1: title, 2: h2, 3: h3}[len(heading[1])]
            story.append(Paragraph(inline(heading[2]), style))
            continue
        if line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph("• " + inline(line[2:]), bullet))
            continue
        paragraph.append(line)
    flush_paragraph()
    if code is not None:
        raise ValueError("Unclosed fenced code block in README.md")

    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=42, rightMargin=42,
                            topMargin=42, bottomMargin=43, title="DSA5208 Project 3 README",
                            author="Jia Siqi and Jia Zeyue", subject=URL)
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
