
import io
import re
import socket
import ipaddress
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


# Safety limits
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_WEBPAGE_SIZE = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_TIMEOUT = 15


SUPPORTED_EXTENSIONS = (
    ".txt", ".pdf", ".png", ".jpg", ".jpeg",
    ".webp", ".tif", ".tiff", ".docx",
    ".pptx", ".xlsx"
)


def _clean_text(text):
    """Clean excessive whitespace from extracted text."""

    text = re.sub(r"\n{3,}", "\n\n", text or "")
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def _validate_public_url(url):
    """Validate URL and reject local/private network destinations."""

    try:
        parsed = urlparse((url or "").strip())

        if parsed.scheme not in ("http", "https"):
            return None, "Only HTTP and HTTPS URLs are supported."

        if not parsed.hostname:
            return None, "Please enter a valid webpage URL."

        if parsed.username or parsed.password:
            return None, "URLs containing login credentials are not allowed."

        host = parsed.hostname.lower()

        if host == "localhost" or host.endswith(
            (".local", ".localhost", ".internal")
        ):
            return None, "Local and private URLs are not supported."

        try:
            port = parsed.port
        except ValueError:
            return None, "Invalid URL port."

        if port is not None and port not in (80, 443):
            return None, "Only standard HTTP and HTTPS ports are allowed."

        # Check literal IP addresses.
        try:
            ip = ipaddress.ip_address(host)

            if not ip.is_global:
                return None, "Private or non-public IP addresses are blocked."

        except ValueError:
            # Resolve domain names and inspect their IP addresses.
            try:
                addresses = socket.getaddrinfo(
                    host,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM
                )

                if not addresses:
                    return None, "Could not resolve webpage address."

                for address in addresses:
                    resolved_ip = ipaddress.ip_address(
                        address[4][0]
                    )

                    if not resolved_ip.is_global:
                        return None, "Private or non-public network addresses are blocked."

            except socket.gaierror:
                return None, "Could not resolve the webpage domain."

        return parsed, None

    except Exception:
        return None, "Invalid webpage URL."


def _extract_ocr(image):
    """Extract English and Hindi text from an image."""

    import pytesseract

    try:
        return pytesseract.image_to_string(
            image,
            lang="eng+hin",
            config="--oem 3 --psm 6"
        ).strip()

    except Exception as error:
        return f"OCR_ERROR: {error}"


def read_uploaded_file(uploaded):
    """Read supported uploaded documents and images."""

    try:
        name = uploaded.name.lower()
        data = uploaded.getvalue()

        if len(data) > MAX_FILE_SIZE:
            return {
                "error": "File is too large. Maximum allowed size is 25 MB."
            }

        if not name.endswith(SUPPORTED_EXTENSIONS):
            return {
                "error": "Unsupported file type."
            }

        if name.endswith(".txt"):
            return {
                "text": _clean_text(
                    data.decode("utf-8", errors="replace")
                )
            }

        if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
            from PIL import Image, ImageOps

            image = Image.open(io.BytesIO(data))
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")

            text = _extract_ocr(image)

            if text.startswith("OCR_ERROR:"):
                return {"error": text.replace("OCR_ERROR: ", "")}

            return {
                "text": _clean_text(text),
                "images": [data]
            }

        if name.endswith(".pdf"):
            import fitz
            from PIL import Image

            doc = fitz.open(stream=data, filetype="pdf")

            try:
                if doc.is_encrypted:
                    return {
                        "error": "Password-protected PDFs are not supported."
                    }

                if len(doc) > 100:
                    return {
                        "error": "PDF has too many pages. Maximum supported is 100."
                    }

                text = "\n".join(
                    page.get_text() for page in doc
                )

                # OCR fallback for scanned PDFs.
                if not text.strip():

                    pages = []

                    try:
                        import pytesseract

                        for page in doc:
                            pix = page.get_pixmap(
                                matrix=fitz.Matrix(2, 2),
                                alpha=False
                            )

                            image = Image.open(
                                io.BytesIO(pix.tobytes("png"))
                            )

                            pages.append(
                                pytesseract.image_to_string(
                                    image,
                                    lang="eng+hin",
                                    config="--oem 3 --psm 6"
                                )
                            )

                        text = "\n".join(pages)

                    except Exception as error:
                        return {
                            "error": (
                                "Scanned PDF OCR failed. "
                                "Check Tesseract installation. "
                                f"Details: {error}"
                            )
                        }

                return {
                    "text": _clean_text(text)
                    or "No readable text found in this PDF."
                }

            finally:
                doc.close()

        if name.endswith(".docx"):
            from docx import Document

            doc = Document(io.BytesIO(data))

            paragraphs = [
                paragraph.text
                for paragraph in doc.paragraphs
                if paragraph.text.strip()
            ]

            # Also read table contents.
            for table in doc.tables:
                for row in table.rows:
                    paragraphs.append(
                        " | ".join(cell.text for cell in row.cells)
                    )

            return {
                "text": _clean_text("\n".join(paragraphs))
            }

        if name.endswith(".pptx"):
            from pptx import Presentation

            prs = Presentation(io.BytesIO(data))
            slides_text = []

            for slide_number, slide in enumerate(prs.slides, start=1):

                slides_text.append(f"[Slide {slide_number}]")

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slides_text.append(shape.text)

            return {
                "text": _clean_text("\n".join(slides_text))
            }

        if name.endswith(".xlsx"):
            from openpyxl import load_workbook

            wb = load_workbook(
                io.BytesIO(data),
                read_only=True,
                data_only=True
            )

            try:
                lines = []

                for ws in wb.worksheets:

                    lines.append(f"[{ws.title}]")

                    for row in ws.iter_rows(values_only=True):
                        values = [
                            str(value)
                            for value in row
                            if value is not None
                        ]

                        if values:
                            lines.append(" | ".join(values))

                return {
                    "text": _clean_text("\n".join(lines))
                }

            finally:
                wb.close()

        return {"error": "Unsupported file type."}

    except Exception as error:
        return {
            "error": f"Could not read file: {error}"
        }


def read_url(url):
    """Read text from a public webpage with redirect validation."""

    current_url = (url or "").strip()

    try:
        session = requests.Session()

        # Do not inherit proxy settings from environment variables.
        session.trust_env = False

        headers = {
            "User-Agent": "TruthLensAI/1.0",
            "Accept": "text/html,application/xhtml+xml"
        }

        for redirect_number in range(MAX_REDIRECTS + 1):

            parsed, validation_error = _validate_public_url(
                current_url
            )

            if validation_error:
                return {"error": validation_error}

            response = session.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                allow_redirects=False,
                stream=True
            )

            try:
                if response.is_redirect or response.is_permanent_redirect:

                    location = response.headers.get("Location")

                    if not location:
                        return {
                            "error": "Webpage returned an invalid redirect."
                        }

                    if redirect_number >= MAX_REDIRECTS:
                        return {
                            "error": "Too many webpage redirects."
                        }

                    current_url = urljoin(
                        current_url,
                        location
                    )

                    continue

                response.raise_for_status()

                content_type = response.headers.get(
                    "Content-Type", ""
                ).lower()

                if not (
                    "text/html" in content_type
                    or "application/xhtml+xml" in content_type
                ):
                    return {
                        "error": "This link does not point to an HTML webpage."
                    }

                content_length = response.headers.get(
                    "Content-Length"
                )

                if content_length:
                    try:
                        if int(content_length) > MAX_WEBPAGE_SIZE:
                            return {
                                "error": "Webpage is too large to process."
                            }
                    except ValueError:
                        pass

                chunks = []
                total_size = 0

                for chunk in response.iter_content(
                    chunk_size=16384
                ):
                    if not chunk:
                        continue

                    total_size += len(chunk)

                    if total_size > MAX_WEBPAGE_SIZE:
                        return {
                            "error": "Webpage exceeded the 2 MB reading limit."
                        }

                    chunks.append(chunk)

                response_data = b"".join(chunks)

                encoding = response.encoding or "utf-8"

                html = response_data.decode(
                    encoding,
                    errors="replace"
                )

                soup = BeautifulSoup(
                    html,
                    "html.parser"
                )

                for tag in soup([
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "noscript",
                    "svg"
                ]):
                    tag.decompose()

                title = (
                    soup.title.get_text(" ", strip=True)
                    if soup.title
                    else parsed.hostname
                )

                text = _clean_text(
                    soup.get_text("\n", strip=True)
                )

                return {
                    "title": title,
                    "text": text[:100000],
                    "url": current_url
                }

            finally:
                response.close()

        return {"error": "Could not complete webpage redirect."}

    except requests.Timeout:
        return {
            "error": "Webpage request timed out. Please try again."
        }

    except requests.RequestException as error:
        return {
            "error": f"Could not read webpage: {error}"
        }

    except Exception as error:
        return {
            "error": f"Unexpected webpage reading error: {error}"
        }

    finally:
        if "session" in locals():
            session.close()
