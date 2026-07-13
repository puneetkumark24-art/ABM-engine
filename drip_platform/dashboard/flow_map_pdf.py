"""
flow_map_pdf.py — renders the ecosystem connection-flow map (same data that
powers bank_flow.html) as a downloadable one-page landscape PDF, styled to
match the BD dossier flow-diagrams: dark navy header bar, four colored
columns, tier badges.

Built with reportlab (already a project dependency, pure-Python — no native
runtime like GTK/Cairo to install) rather than an HTML-to-PDF engine like
weasyprint, specifically to avoid a repeat of the Tesseract-style
native-dependency install problem on Windows.
"""
from __future__ import annotations
import io
from datetime import datetime

from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

PAGE_W, PAGE_H = landscape(A4)

NAVY = HexColor("#0B1F3A")
GOLD = HexColor("#D4A017")
LIGHT_BLUE = HexColor("#C9D6E8")
CARD_TEXT = HexColor("#E8ECF2")
COL_COLORS = {
    "decimal": HexColor("#0B1F3A"),
    "connectors": HexColor("#B8860B"),
    "champions": HexColor("#7A1F1F"),
    "csuite": HexColor("#1B3A5C"),
}
CARD_BG = HexColor("#F4F1EA")
TEXT_DARK = HexColor("#1A1A1A")


def _wrap(c, text, x, y, max_width, font="Helvetica", size=8, color=TEXT_DARK, leading=None):
    leading = leading or size + 2
    c.setFont(font, size)
    c.setFillColor(color)
    for line in simpleSplit(text or "", font, size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def render_flow_map_pdf(org, flow_data: dict) -> bytes:
    """org: models.Organization. flow_data: the dict returned by
    app.build_flow_map_data() — connectors, subsidiary_groups, c_suite,
    decimal_items, summary_line. Returns raw PDF bytes."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    margin = 24
    header_h = 66
    footer_h = 24

    # ── Header bar ──
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - header_h, PAGE_W, header_h, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 17)
    title = f"{org.canonical_name.upper()} × DECIMAL — CONNECTION-FLOW MAP"
    c.drawString(margin, PAGE_H - 28, title[:110])
    c.setFont("Helvetica", 9)
    c.setFillColor(LIGHT_BLUE)
    c.drawString(margin, PAGE_H - 45, (flow_data.get("summary_line") or "")[:160])
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(PAGE_W - margin, PAGE_H - 20, "CONFIDENTIAL — NOT FOR DISTRIBUTION")
    c.setFillColor(LIGHT_BLUE)
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - margin, PAGE_H - 32,
                       f"Decimal Technologies BD · generated {datetime.utcnow().strftime('%d %b %Y')}")

    # ── Columns ──
    columns = [
        ("decimal", "DECIMAL", flow_data.get("decimal_items", []) or [], "list"),
        ("connectors", "EXTERNAL CONNECTORS", flow_data.get("connectors", []) or [], "person"),
        ("champions", "SUBSIDIARY CHAMPIONS", flow_data.get("subsidiary_groups", []) or [], "group"),
        ("csuite", "C-SUITE TARGETS", flow_data.get("c_suite", []) or [], "person"),
    ]
    n = len(columns)
    gutter = 14
    col_w = (PAGE_W - 2 * margin - gutter * (n - 1)) / n
    top_y = PAGE_H - header_h - 14
    bottom_y = footer_h + 10

    for i, (key, label, items, kind) in enumerate(columns):
        x = margin + i * (col_w + gutter)
        color = COL_COLORS[key]

        c.setFillColor(color)
        c.roundRect(x, top_y - 22, col_w, 22, 4, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + col_w / 2, top_y - 15, label)

        y = top_y - 22 - 8

        if not items:
            c.setFillColor(CARD_BG)
            c.roundRect(x, y - 24, col_w, 24, 4, stroke=0, fill=1)
            c.setFont("Helvetica-Oblique", 7.5)
            c.setFillColor(HexColor("#94A3B8"))
            c.drawString(x + 8, y - 15, "Nothing loaded yet")
            continue

        if kind == "list":
            box_h = max(24, 18 * len(items) + 12)
            box_bottom = max(bottom_y, y - box_h)
            c.setFillColor(CARD_BG)
            c.roundRect(x, box_bottom, col_w, y - box_bottom, 4, stroke=0, fill=1)
            yy = y - 12
            for item in items:
                yy = _wrap(c, "• " + item, x + 8, yy, col_w - 16, size=8)
                yy -= 3
                if yy < box_bottom + 6:
                    break

        elif kind == "person":
            for p in items:
                card_h = 46
                if y - card_h < bottom_y:
                    break
                c.setFillColor(color)
                c.roundRect(x, y - card_h, col_w, card_h, 3, stroke=0, fill=1)
                c.setFillColor(white)
                c.setFont("Helvetica-Bold", 8.5)
                c.drawString(x + 6, y - 12, (p.get("full_name") or "")[:34])
                badge = "CEO" if p.get("bd_priority") == "Final Authority" else p.get("bd_priority")
                if badge:
                    c.setFont("Helvetica-Bold", 7)
                    c.drawRightString(x + col_w - 6, y - 12, str(badge)[:12])
                c.setFont("Helvetica", 7)
                c.setFillColor(CARD_TEXT)
                c.drawString(x + 6, y - 22, (p.get("current_title") or "")[:42])
                if p.get("org_name"):
                    c.drawString(x + 6, y - 31, p["org_name"][:42])
                contact = p.get("phone") or p.get("primary_email") or ""
                if contact:
                    c.setFont("Helvetica", 6.5)
                    c.drawString(x + 6, y - 40, contact[:46])
                y -= card_h + 6

        elif kind == "group":
            for g in items:
                members = g.get("members", []) or []
                card_h = 26 + 13 * max(len(members), 1)
                if y - card_h < bottom_y:
                    break
                c.setFillColor(color)
                c.roundRect(x, y - card_h, col_w, card_h, 3, stroke=0, fill=1)
                c.setFillColor(white)
                c.setFont("Helvetica-Bold", 8.5)
                header_txt = (g.get("canonical_name") or "")[:30]
                if g.get("stars"):
                    header_txt += "  " + g["stars"]
                c.drawString(x + 6, y - 13, header_txt)
                yy = y - 25
                c.setFont("Helvetica", 7)
                c.setFillColor(CARD_TEXT)
                for m in members:
                    line = m.get("full_name") or ""
                    if m.get("current_title"):
                        line += " — " + m["current_title"]
                    c.drawString(x + 10, yy, line[:50])
                    yy -= 13
                y -= card_h + 6

    # ── Footer ──
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, footer_h, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(margin, 8, "CONFIDENTIAL — NOT FOR DISTRIBUTION — DECIMAL TECHNOLOGIES BD RESEARCH")
    c.setFillColor(white)
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - margin, 8, "Connection-Flow Map · Page 1")

    c.showPage()
    c.save()
    return buf.getvalue()
