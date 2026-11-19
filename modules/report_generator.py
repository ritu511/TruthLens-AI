
from io import BytesIO
from xml.sax.saxutils import escape
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether
)


def generate_pdf_report(report_data):
    """Generate a downloadable TruthLens AI verification report."""

    if not isinstance(report_data, dict):
        raise ValueError("Invalid report data.")

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontSize=23,
        leading=28,
        textColor=colors.HexColor("#1D4ED8"),
        alignment=TA_CENTER,
        spaceAfter=8
    ))

    styles.add(ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1D4ED8"),
        spaceBefore=12,
        spaceAfter=7
    ))

    styles.add(ParagraphStyle(
        name="BodyTextCustom",
        parent=styles["BodyText"],
        fontSize=9,
        leading=14,
        spaceAfter=6,
        wordWrap="CJK"
    ))

    styles.add(ParagraphStyle(
        name="SourceHeading",
        parent=styles["Heading4"],
        fontSize=10,
        leading=13,
        spaceBefore=6,
        spaceAfter=4
    ))

    story = []

    def safe(value):
        """Escape values before inserting them into ReportLab paragraphs."""
        return escape(str(value if value is not None else ""))

    def add_paragraph(value):
        story.append(
            Paragraph(safe(value), styles["BodyTextCustom"])
        )

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawRightString(
            A4[0] - 18 * mm,
            10 * mm,
            f"Page {doc.page}"
        )
        canvas.restoreState()

    # Header
    story.append(Paragraph(
        "TRUTHLENS AI",
        styles["ReportTitle"]
    ))

    story.append(Paragraph(
        "Content Investigation & Verification Report",
        styles["Heading3"]
    ))

    story.append(Spacer(1, 8))

    story.append(HRFlowable(
        width="100%",
        color=colors.HexColor("#CBD5E1")
    ))

    story.append(Spacer(1, 12))

    add_paragraph(
        "Report generated: " +
        datetime.now().strftime("%d %B %Y, %I:%M %p")
    )

    # Claim details
    story.append(Paragraph(
        "1. Claim Details",
        styles["SectionHeading"]
    ))

    add_paragraph(
        report_data.get("claim", "Not provided")
    )

    # Evidence assessment
    story.append(Paragraph(
        "2. Evidence Assessment",
        styles["SectionHeading"]
    ))

    add_paragraph(
        "Assessment: " +
        str(report_data.get("status", "Inconclusive"))
    )

    counts = report_data.get("counts", {})

    if not isinstance(counts, dict):
        counts = {}

    table_data = [
        ["Evidence Type", "Count"],
        ["Supports", counts.get("Supports", 0)],
        ["Contradicts", counts.get("Contradicts", 0)],
        ["Context only", counts.get("Context only", 0)],
        ["Unclear", counts.get("Unclear", 0)]
    ]

    table = Table(
        table_data,
        colWidths=[100 * mm, 45 * mm],
        repeatRows=1
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
    ]))

    story.append(table)

    # Sources
    story.append(Paragraph(
        "3. Collected Sources",
        styles["SectionHeading"]
    ))

    sources = report_data.get("sources", [])

    if not isinstance(sources, list):
        sources = []

    valid_sources = [
        source for source in sources
        if isinstance(source, dict)
    ]

    if valid_sources:

        for number, source in enumerate(valid_sources, start=1):

            source_content = [
                Paragraph(
                    f"Source {number}",
                    styles["SourceHeading"]
                ),
                Paragraph(
                    safe("Title: " + str(
                        source.get("title", "Untitled")
                    )),
                    styles["BodyTextCustom"]
                ),
                Paragraph(
                    safe("URL: " + str(
                        source.get("url", "Not provided")
                    )),
                    styles["BodyTextCustom"]
                ),
                Paragraph(
                    safe("Relationship: " + str(
                        source.get("relation", "Unclear")
                    )),
                    styles["BodyTextCustom"]
                ),
                Paragraph(
                    safe("Evidence: " + str(
                        source.get("excerpt", "")
                    )),
                    styles["BodyTextCustom"]
                ),
                Spacer(1, 6)
            ]

            story.append(KeepTogether(source_content))

    else:
        add_paragraph("No evidence sources were collected.")

    # Source summary
    story.append(Paragraph(
        "4. Source Summary",
        styles["SectionHeading"]
    ))

    add_paragraph(
        "Unique domains: " +
        str(report_data.get("unique_domains", 0))
    )

    domains = report_data.get("domains", [])

    if not isinstance(domains, list):
        domains = []

    add_paragraph(
        "Domains: " +
        (", ".join(str(domain) for domain in domains) if domains else "None")
    )

    # Limitations
    story.append(Paragraph(
        "5. Important Limitations",
        styles["SectionHeading"]
    ))

    add_paragraph(
        "This report summarizes evidence relationships selected "
        "by the user. It does not independently establish whether "
        "a claim is true or false. Source credibility indicators, "
        "text similarity and image analysis are not proof of authenticity."
    )

    story.append(Spacer(1, 15))

    story.append(Paragraph(
        "Generated by TruthLens AI",
        styles["Italic"]
    ))

    document.build(
        story,
        onFirstPage=add_page_number,
        onLaterPages=add_page_number
    )

    buffer.seek(0)

    return buffer.getvalue()
