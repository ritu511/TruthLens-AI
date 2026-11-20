
import io
from functools import lru_cache

import torch

from PIL import (
    Image,
    ImageChops,
    ImageEnhance,
    ImageFilter,
    ImageStat,
    ExifTags,
    UnidentifiedImageError
)


MODEL_NAME = "aaronkantrowitz/ai-human-generated-image-detection"


def extract_image_metadata(image):
    """Extract basic image metadata and EXIF information."""

    metadata = {
        "format": image.format or "Unknown",
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "exif": {}
    }

    try:
        for tag_id, value in image.getexif().items():

            tag_name = ExifTags.TAGS.get(
                tag_id,
                str(tag_id)
            )

            if not isinstance(value, bytes):
                metadata["exif"][tag_name] = str(value)

    except Exception:
        pass

    return metadata


def analyze_image_quality(image):
    """Calculate basic edge and texture measurements."""

    grayscale = image.convert("L")
    edge_image = grayscale.filter(ImageFilter.FIND_EDGES)
    statistics = ImageStat.Stat(edge_image)

    return {
        "edge_mean": round(statistics.mean[0], 2),
        "edge_variance": round(statistics.var[0], 2),
        "description": (
            "Edge and texture measurements. "
            "These values do not prove manipulation."
        )
    }


def generate_ela(image, quality=90):
    """
    Generate Error Level Analysis visualization.

    ELA is a visual inspection aid, not proof of manipulation.
    """

    if image.format != "JPEG":
        return None

    original = image.convert("RGB")
    buffer = io.BytesIO()

    original.save(
        buffer,
        format="JPEG",
        quality=quality
    )

    buffer.seek(0)

    with Image.open(buffer) as recompressed_image:
        recompressed = recompressed_image.convert("RGB")

    difference = ImageChops.difference(
        original,
        recompressed
    )

    statistics = ImageStat.Stat(difference)

    max_difference = max(
        max(channel) for channel in statistics.extrema
    )

    if max_difference > 0:
        difference = ImageEnhance.Brightness(
            difference
        ).enhance(255.0 / max_difference)

    return difference


@lru_cache(maxsize=1)
def load_ai_classifier():
    """Load and cache the Hugging Face image classifier."""

    from transformers import pipeline

    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    return pipeline(
        "image-classification",
        model=MODEL_NAME,
        device=device
    )


def detect_ai_image(image):
    """
    Run experimental AI-image classification.

    Model predictions are indicators, not proof of image origin.
    """

    try:
        classifier = load_ai_classifier()

        predictions = classifier(
            image.convert("RGB")
        )

        if not isinstance(predictions, list):
            raise ValueError("Unexpected model output.")

        ai_score = 0.0
        human_score = 0.0
        ai_label_found = False
        human_label_found = False

        for item in predictions:

            label = str(item.get("label", "")).lower()
            score = float(item.get("score", 0.0))

            if not 0 <= score <= 1:
                continue

            if any(word in label for word in (
                "ai", "artificial", "fake", "synthetic", "generated"
            )):
                ai_score += score
                ai_label_found = True

            elif any(word in label for word in (
                "human", "real", "natural", "photograph"
            )):
                human_score += score
                human_label_found = True

        if not ai_label_found or not human_label_found:
            return {
                "available": False,
                "error": (
                    "The model labels could not be reliably mapped "
                    "to both AI-generated and human-generated classes."
                )
            }

        prediction = (
            "AI-generated indicators detected"
            if ai_score > human_score
            else "Human-generated indicators detected"
        )

        return {
            "available": True,
            "prediction": prediction,
            "ai_score": round(ai_score * 100, 2),
            "human_score": round(human_score * 100, 2),
            "model": MODEL_NAME,
            "warning": (
                "Experimental model prediction only. "
                "It does not prove whether an image is AI-generated "
                "or human-created. Results may be incorrect, "
                "especially for edited or compressed images."
            )
        }

    except Exception as error:
        return {
            "available": False,
            "error": str(error)
        }


def analyze_image(image_bytes):
    """
    Main image-forensics function.

    Returns a structured result compatible with app.py.
    """

    try:
        if not isinstance(image_bytes, (bytes, bytearray)):
            raise ValueError("Invalid image file data.")

        if not image_bytes:
            raise ValueError("The uploaded image is empty.")

        with Image.open(io.BytesIO(image_bytes)) as source_image:

            source_image.load()

            # Keep original format for metadata and ELA.
            original_format = source_image.format

            image = source_image.copy()
            image.format = original_format

        metadata = extract_image_metadata(image)

        quality = analyze_image_quality(image)

        ela_image = generate_ela(image)

        ai_detection = detect_ai_image(image)

        warnings = []

        if not metadata["exif"]:
            warnings.append(
                "No EXIF metadata found. It may have been removed."
            )

        if ela_image is None:
            warnings.append(
                "ELA is available only for JPEG images."
            )

        warnings.append(
            "AI detection is experimental and cannot prove "
            "whether an image is AI-generated."
        )

        warnings.append(
            "Metadata and image quality measurements are "
            "indicators, not proof of manipulation."
        )

        return {
            "success": True,
            "metadata": metadata,
            "quality": quality,
            "ela_available": ela_image is not None,
            "ela_image": ela_image,
            "ai_detection": ai_detection,
            "file_size_kb": round(len(image_bytes) / 1024, 2),
            "warnings": warnings
        }

    except (UnidentifiedImageError, OSError):
        return {
            "success": False,
            "error": "The uploaded file is not a valid readable image."
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }
