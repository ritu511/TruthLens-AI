
import os
import shutil

import pytesseract
from PIL import Image, ImageOps, ImageEnhance


def find_tesseract():
    """Find Tesseract executable on macOS or system PATH."""

    path = shutil.which("tesseract")

    if path:
        return path

    possible_paths = [
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract"
    ]

    for path in possible_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None


TESSERACT_PATH = find_tesseract()

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


def get_ocr_languages():
    """Return available OCR languages."""

    if not TESSERACT_PATH:
        return []

    try:
        return pytesseract.get_languages(config="")
    except Exception:
        return []


def extract_text(image: Image.Image) -> str:
    """
    Extract text from an image using Tesseract OCR.

    Uses English and Hindi when both language packs
    are installed. Falls back to available languages.
    """

    try:
        if not TESSERACT_PATH:
            return (
                "ERROR: Tesseract executable not found. "
                "Please install Tesseract using Homebrew."
            )

        if not isinstance(image, Image.Image):
            return "ERROR: Invalid image provided for OCR."

        available_languages = get_ocr_languages()

        selected_languages = [
            language
            for language in ("eng", "hin")
            if language in available_languages
        ]

        if not selected_languages:
            return (
                "ERROR: No supported OCR language data found. "
                "Please install English or Hindi language data."
            )

        image = image.convert("RGB")
        image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image)
        image = ImageEnhance.Contrast(image).enhance(1.5)

        language_config = "+".join(selected_languages)

        text = pytesseract.image_to_string(
            image,
            lang=language_config,
            config="--oem 3 --psm 6"
        )

        return text.strip()

    except Exception as error:
        return f"ERROR: OCR failed: {error}"
