"""Professional PDF reports for TruthLens AI, with Unicode Hindi support."""
from io import BytesIO
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from urllib.parse import urlparse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)

NAVY = colors.HexColor("#102B3A")
TEAL = colors.HexColor("#007F91")
PALE = colors.HexColor("#EAF8FC")
MUTED = colors.HexColor("#557181")
BORDER = colors.HexColor("#CBE7EE")
GREEN = colors.HexColor("#087F5B")
AMBER = colors.HexColor("#9A6700")


def _register_unicode_font():
    """Register a Devanagari-capable Noto font when available on the host."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari[wdth,wght].ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                if "TruthLensNoto" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(
                        TTFont("TruthLensNoto", candidate, shapable=True)
                    )
                    pdfmetrics.registerFontFamily(
                        "TruthLensNoto", normal="TruthLensNoto",
                        bold="TruthLensNoto", italic="TruthLensNoto",
                        boldItalic="TruthLensNoto",
                    )
                return "TruthLensNoto"
            except Exception:
                continue
    return "Helvetica"


def _styles(font_name):
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TLTitle", parent=base["Title"], fontName=font_name,
            fontSize=24, leading=29, textColor=colors.white,
            alignment=TA_LEFT, spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "TLSubtitle", parent=base["Normal"], fontName=font_name,
            fontSize=10, leading=15, textColor=colors.HexColor("#D7F5F8"),
        ),
        "section": ParagraphStyle(
            "TLSection", parent=base["Heading2"], fontName=font_name,
            fontSize=13, leading=17, textColor=TEAL,
            spaceBefore=13, spaceAfter=7,
        ),
        "body": ParagraphStyle(
            "TLBody", parent=base["BodyText"], fontName=font_name,
            fontSize=9.2, leading=14, textColor=NAVY,
            spaceAfter=5, wordWrap="CJK", shaping=1,
        ),
        "small": ParagraphStyle(
            "TLSmall", parent=base["BodyText"], fontName=font_name,
            fontSize=8, leading=11, textColor=MUTED,
            spaceAfter=3, wordWrap="CJK", shaping=1,
        ),
        "card": ParagraphStyle(
            "TLCard", parent=base["BodyText"], fontName=font_name,
            fontSize=9, leading=13, textColor=NAVY,
            spaceAfter=4, wordWrap="CJK", shaping=1,
        ),
    }


def _safe(value):
    return escape(str(value if value is not None else "")).replace("\n", "<br/>")


def _footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, 15 * mm, width - 18 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "TRUTHLENS AI  |  Content Investigation")
    canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _header(story, styles, subtitle):
    banner = Table(
        [[
            Paragraph("TRUTHLENS AI", styles["title"]),
            Paragraph(_safe(subtitle), styles["subtitle"]),
        ]],
        colWidths=[72 * mm, 78 * mm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
    ]))
    story.extend([banner, Spacer(1, 10)])


def _metric_table(counts, styles):
    rows = [[
        Paragraph("<b>SUPPORTS</b><br/>" + str(counts.get("Supports", 0)), styles["card"]),
        Paragraph("<b>CONTRADICTS</b><br/>" + str(counts.get("Contradicts", 0)), styles["card"]),
        Paragraph("<b>CONTEXT ONLY</b><br/>" + str(counts.get("Context only", 0)), styles["card"]),
        Paragraph("<b>UNCLEAR</b><br/>" + str(counts.get("Unclear", 0)), styles["card"]),
    ]]
    table = Table(rows, colWidths=[37.5 * mm] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def generate_pdf_report(report_data):
    """Generate a polished single-claim PDF report."""
    if not isinstance(report_data, dict):
        raise ValueError("Invalid report data.")
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=21 * mm,
        title="TruthLens AI - Claim Verification Report",
        author="TruthLens AI",
    )
    font_name = _register_unicode_font()
    styles = _styles(font_name)
    story = []
    _header(story, styles, "CLAIM VERIFICATION REPORT")
    story.append(Paragraph(
        "Generated: " + _safe(datetime.now().strftime("%d %B %Y · %I:%M %p")),
        styles["small"],
    ))
    story.append(HRFlowable(width="100%", color=BORDER, thickness=0.8, spaceBefore=3, spaceAfter=5))

    story.append(Paragraph("01  Claim under review", styles["section"]))
    claim_card = Table([[Paragraph(_safe(report_data.get("claim", "Not provided")), styles["body"])]], colWidths=[150 * mm])
    claim_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(claim_card)

    story.append(Paragraph("02  Evidence assessment", styles["section"]))
    status = str(report_data.get("status", "Insufficient Evidence"))
    story.append(Paragraph("<b>Current assessment:</b> " + _safe(status), styles["body"]))
    counts = report_data.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    story.append(_metric_table(counts, styles))
    story.append(Paragraph(
        "Evidence records included: " + str(sum(int(counts.get(k, 0) or 0) for k in ("Supports", "Contradicts", "Context only", "Unclear"))),
        styles["small"],
    ))

    story.append(Paragraph("03  Collected source material", styles["section"]))
    sources = report_data.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    sources = [row for row in sources if isinstance(row, dict)]
    if not sources:
        story.append(Paragraph("No evidence records were matched to this claim at report-generation time.", styles["body"]))
    else:
        for index, source in enumerate(sources, start=1):
            domain = urlparse(str(source.get("url", ""))).netloc or "Domain not available"
            content = [
                Paragraph(f"<b>Source {index}: {_safe(source.get('title') or 'Untitled source')}</b>", styles["card"]),
                Paragraph("<b>Relationship:</b> " + _safe(source.get("relation", "Unclear")), styles["card"]),
                Paragraph("<b>Domain:</b> " + _safe(domain), styles["small"]),
                Paragraph("<b>URL:</b> " + _safe(source.get("url", "Not provided")), styles["small"]),
                Paragraph("<b>Evidence excerpt:</b> " + _safe(source.get("excerpt", "No excerpt provided")), styles["card"]),
            ]
            card = Table([[content]], colWidths=[150 * mm])
            card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("LINEBEFORE", (0, 0), (0, 0), 3, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.extend([KeepTogether([card]), Spacer(1, 6)])

    domains = report_data.get("domains", [])
    if not isinstance(domains, list):
        domains = []
    story.append(Paragraph("04  Source overview", styles["section"]))
    story.append(Paragraph(
        "Unique domains: " + str(report_data.get("unique_domains", len(set(domains)))),
        styles["body"],
    ))
    story.append(Paragraph("Domains: " + _safe(", ".join(map(str, domains)) if domains else "Not available"), styles["body"]))

    story.append(Paragraph("05  Methodology and limitations", styles["section"]))
    story.append(Paragraph(
        "This report records evidence material and relationship labels associated with the selected claim. "
        "A Supports or Contradicts label is a user-selected classification, not an independent fact-check. "
        "HTTPS, domain categories, source indicators and text overlap do not prove that a claim is true or false. "
        "Review the original sources and seek independent corroboration.",
        styles["body"],
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Prepared by TruthLens AI · Content Investigation Workspace", styles["small"]))

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_investigation_pdf(report_data):
    """Generate a polished multi-claim investigation report."""
    if not isinstance(report_data, dict):
        raise ValueError("Invalid investigation report data.")
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=21 * mm,
        title="TruthLens AI - Complete Investigation Report",
        author="TruthLens AI",
    )
    font_name = _register_unicode_font()
    styles = _styles(font_name)
    story = []
    _header(story, styles, "COMPLETE INVESTIGATION REPORT")
    story.append(Paragraph("Investigation: " + _safe(report_data.get("title", "Untitled")), styles["body"]))
    story.append(Paragraph("Source: " + _safe(report_data.get("source_name", "Not specified")), styles["body"]))
    story.append(Paragraph("Generated: " + _safe(datetime.now().strftime("%d %B %Y · %I:%M %p")), styles["small"]))

    claims = report_data.get("claims", [])
    evidence = report_data.get("evidence", [])
    claims = claims if isinstance(claims, list) else []
    evidence = evidence if isinstance(evidence, list) else []
    story.append(Paragraph("01  Investigation snapshot", styles["section"]))
    story.append(Paragraph(f"Candidate claims: {len(claims)}  |  Evidence records: {len(evidence)}", styles["body"]))

    story.append(Paragraph("02  Claim-by-claim review", styles["section"]))
    for index, item in enumerate(claims, start=1):
        claim = item.get("claim", "") if isinstance(item, dict) else str(item)
        related = [row for row in evidence if isinstance(row, dict) and " ".join(str(row.get("claim", "")).split()).casefold() == " ".join(str(claim).split()).casefold()]
        counts = {"Supports": 0, "Contradicts": 0, "Context only": 0, "Unclear": 0}
        for row in related:
            relation = row.get("relation", "Unclear")
            counts[relation if relation in counts else "Unclear"] += 1
        story.append(Paragraph(f"<b>Claim {index}</b>", styles["card"]))
        story.append(Paragraph(_safe(claim), styles["body"]))
        story.append(_metric_table(counts, styles))
        story.append(Spacer(1, 7))
        if not related:
            story.append(Paragraph("No evidence records were matched to this claim.", styles["small"]))

    story.append(Paragraph("03  Evidence register", styles["section"]))
    if evidence:
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                continue
            group = [
                Paragraph(f"<b>Evidence {index}: {_safe(item.get('title') or 'Untitled source')}</b>", styles["card"]),
                Paragraph("<b>Claim:</b> " + _safe(item.get("claim", "")), styles["card"]),
                Paragraph("<b>Relationship:</b> " + _safe(item.get("relation", "Unclear")), styles["card"]),
                Paragraph("<b>URL:</b> " + _safe(item.get("url", "")), styles["small"]),
                Paragraph("<b>Excerpt:</b> " + _safe(item.get("excerpt", "")), styles["card"]),
            ]
            card = Table([[group]], colWidths=[150 * mm])
            card.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("LINEBEFORE", (0, 0), (0, 0), 3, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.extend([card, Spacer(1, 6)])
    else:
        story.append(Paragraph("No evidence records were collected.", styles["body"]))

    story.append(Paragraph("04  Methodology and limitations", styles["section"]))
    story.append(Paragraph(
        "Candidate claims are suggestions for investigation, not verified facts. Evidence relationships are selected by the user. "
        "Domain and HTTPS indicators do not establish publisher reputation or factual accuracy. "
        "Text overlap is not semantic proof; consult original sources and independent corroboration.",
        styles["body"],
    ))
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.getvalue()
