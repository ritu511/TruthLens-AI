
from io import BytesIO
from pathlib import Path

import fitz
import pandas as pd
from PIL import Image, UnidentifiedImageError
from docx import Document
from pptx import Presentation

from modules.ocr import extract_text


MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_PDF_PAGES = 100

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf", ".docx", ".txt", ".pptx", ".xlsx"
}


def read_text_file(file_bytes):
    """Read a TXT file with common text encodings."""

    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return file_bytes.decode("utf-8", errors="replace")


def read_docx(file_bytes):
    """Extract paragraphs and tables from DOCX."""

    document = Document(BytesIO(file_bytes))
    output = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            output.append(text)

    for table_number, table in enumerate(document.tables, start=1):
        output.append(f"\n[TABLE {table_number}]")

        for row in table.rows:
            cells = [
                cell.text.strip().replace("\n", " ")
                for cell in row.cells
            ]

            output.append(" | ".join(cells))

    return "\n".join(output)


def read_pptx(file_bytes):
    """Extract text from PowerPoint slides."""

    presentation = Presentation(BytesIO(file_bytes))
    output = []

    for slide_number, slide in enumerate(
        presentation.slides, start=1
    ):
        output.append(f"\n--- SLIDE {slide_number} ---")

        for shape in slide.shapes:

            if shape.has_table:
                for row in shape.table.rows:
                    cells = [
                        cell.text.strip()
                        for cell in row.cells
                    ]

                    output.append(" | ".join(cells))

            elif hasattr(shape, "text"):
                text = shape.text.strip()

                if text:
                    output.append(text)

    return "\n".join(output)


def read_xlsx(file_bytes):
    """Extract values from Excel worksheets."""

    output = []

    with pd.ExcelFile(
        BytesIO(file_bytes),
        engine="openpyxl"
    ) as workbook:

        for sheet_name in workbook.sheet_names:

            dataframe = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                header=None,
                dtype=str
            )

            output.append(f"\n--- SHEET: {sheet_name} ---")

            for row in dataframe.fillna("").values.tolist():

                values = [
                    str(value).strip()
                    for value in row
                ]

                if any(values):
                    output.append(" | ".join(values))

    return "\n".join(output)


def read_pdf(file_bytes):
    """
    Extract selectable PDF text first.
    Use OCR for pages containing little or no selectable text.
    """

    output = []

    with fitz.open(
        stream=file_bytes,
        filetype="pdf"
    ) as pdf:

        if pdf.is_encrypted:
            raise ValueError(
                "Password-protected PDFs are not supported."
            )

        if len(pdf) == 0:
            raise ValueError("The PDF contains no pages.")

        if len(pdf) > MAX_PDF_PAGES:
            raise ValueError(
                f"PDF page limit exceeded. Maximum allowed: "
                f"{MAX_PDF_PAGES} pages."
            )

        for page_number, page in enumerate(pdf):

            page_text = page.get_text("text") or ""

            if len(page_text.strip()) >= 20:
                output.append(
                    f"\n--- PAGE {page_number + 1} ---\n"
                    f"{page_text.strip()}"
                )
                continue

            # Render scanned PDF page for OCR.
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(2, 2),
                alpha=False
            )

            image = Image.frombytes(
                "RGB",
                [pixmap.width, pixmap.height],
                pixmap.samples
            )

            ocr_text = extract_text(image)

            output.append(
                f"\n--- PAGE {page_number + 1} (OCR) ---\n"
                f"{ocr_text or ''}"
            )

    return "\n".join(output)


def read_image(file_bytes):
    """Extract text from an uploaded image using OCR."""

    try:
        with Image.open(BytesIO(file_bytes)) as image:
            image.load()
            return extract_text(image.convert("RGB"))

    except UnidentifiedImageError:
        raise ValueError("The uploaded image is invalid.")

    except OSError:
        raise ValueError("Unable to open the uploaded image.")


def extract_file_content(uploaded_file):
    """
    Main file reader.

    Returns extracted text as a string.
    Errors are returned as strings beginning with ERROR:
    """

    try:
        if uploaded_file is None:
            return "ERROR: No file was uploaded."

        filename = getattr(uploaded_file, "name", "")

        if not filename:
            return "ERROR: Invalid file name."

        extension = Path(filename).suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            return f"ERROR: Unsupported file format: {extension}"

        file_bytes = uploaded_file.getvalue()

        if not file_bytes:
            return "ERROR: The uploaded file is empty."

        if len(file_bytes) > MAX_FILE_SIZE:
            return "ERROR: File size exceeds the 25 MB limit."

        if extension == ".txt":
            extracted_text = read_text_file(file_bytes)

        elif extension == ".pdf":
            extracted_text = read_pdf(file_bytes)

        elif extension == ".docx":
            extracted_text = read_docx(file_bytes)

        elif extension == ".pptx":
            extracted_text = read_pptx(file_bytes)

        elif extension == ".xlsx":
            extracted_text = read_xlsx(file_bytes)

        else:
            extracted_text = read_image(file_bytes)

        if not isinstance(extracted_text, str):
            return "ERROR: File extraction returned an invalid result."

        if not extracted_text.strip():
            return "ERROR: No readable text was found in this file."

        return extracted_text.strip()

    except Exception as error:
        return f"ERROR: Unable to read file: {str(error)}"
