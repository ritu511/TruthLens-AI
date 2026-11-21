
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


def generate_investigation_pdf(report_data):
    """Generate a complete multi-claim investigation report."""
    if not isinstance(report_data, dict):
        raise ValueError("Invalid investigation report data.")

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="InvestigationTitle", parent=styles["Title"],
        fontSize=21, leading=26, textColor=colors.HexColor("#007F91"),
        alignment=TA_CENTER, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="InvestigationSection", parent=styles["Heading2"],
        fontSize=13, leading=17, textColor=colors.HexColor("#007F91"),
        spaceBefore=13, spaceAfter=7,
    ))
    styles.add(ParagraphStyle(
        name="InvestigationBody", parent=styles["BodyText"],
        fontSize=9, leading=13, spaceAfter=5, wordWrap="CJK",
    ))

    def safe(value):
        return escape(str(value if value is not None else ""))

    story = [
        Paragraph("TRUTHLENS AI", styles["InvestigationTitle"]),
        Paragraph("Complete Content Investigation Report", styles["Heading3"]),
        Spacer(1, 8),
        HRFlowable(width="100%", color=colors.HexColor("#9DDCE5")),
        Spacer(1, 10),
        Paragraph("Investigation: " + safe(report_data.get("title", "Untitled")), styles["InvestigationBody"]),
        Paragraph("Generated: " + safe(datetime.now().strftime("%d %B %Y, %I:%M %p")), styles["InvestigationBody"]),
        Paragraph("Source: " + safe(report_data.get("source_name", "Not specified")), styles["InvestigationBody"]),
        Paragraph("Important: This report summarizes collected material and user-selected evidence relationships. It is not an independent determination of truth.", styles["InvestigationBody"]),
    ]

    claims = report_data.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    evidence = report_data.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    story.append(Paragraph("1. Investigation overview", styles["InvestigationSection"]))
    story.append(Paragraph("Candidate claims: " + str(len(claims)), styles["InvestigationBody"]))
    story.append(Paragraph("Evidence records: " + str(len(evidence)), styles["InvestigationBody"]))

    story.append(Paragraph("2. Candidate claims and evidence assessment", styles["InvestigationSection"]))
    if claims:
        for index, item in enumerate(claims, start=1):
            claim = item.get("claim", "") if isinstance(item, dict) else str(item)
            story.append(Paragraph(f"Claim {index}: " + safe(claim), styles["InvestigationBody"]))
            related = [row for row in evidence if isinstance(row, dict) and row.get("claim") == claim]
            counts = {"Supports": 0, "Contradicts": 0, "Context only": 0, "Unclear": 0}
            for row in related:
                relation = row.get("relation", "Unclear")
                if relation not in counts:
                    relation = "Unclear"
                counts[relation] += 1
            story.append(Paragraph("Evidence counts: " + safe(", ".join(f"{key}: {value}" for key, value in counts.items())), styles["InvestigationBody"]))
            if not related:
                story.append(Paragraph("No evidence records were saved for this claim.", styles["InvestigationBody"]))
    else:
        story.append(Paragraph("No candidate claims were saved.", styles["InvestigationBody"]))

    story.append(Paragraph("3. Collected evidence and sources", styles["InvestigationSection"]))
    if evidence:
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                continue
            story.append(Paragraph(f"Evidence {index}: " + safe(item.get("title", "Untitled source")), styles["Heading4"]))
            story.append(Paragraph("Claim: " + safe(item.get("claim", "")), styles["InvestigationBody"]))
            story.append(Paragraph("Relationship: " + safe(item.get("relation", "Unclear")), styles["InvestigationBody"]))
            story.append(Paragraph("URL: " + safe(item.get("url", "")), styles["InvestigationBody"]))
            story.append(Paragraph("Excerpt: " + safe(item.get("excerpt", "")), styles["InvestigationBody"]))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("No evidence records were collected.", styles["InvestigationBody"]))

    story.append(Paragraph("4. Methodology and limitations", styles["InvestigationSection"]))
    for note in [
        "Candidate claim extraction identifies statements for review; it does not verify them.",
        "Evidence relationship labels are selected by the user and may require correction.",
        "Source domain and HTTPS indicators do not establish factual accuracy or editorial reliability.",
        "Lexical overlap is not semantic proof. Review original sources and seek independent corroboration.",
    ]:
        story.append(Paragraph("• " + safe(note), styles["InvestigationBody"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64808A"))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"TruthLens AI · Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer.getvalue()
