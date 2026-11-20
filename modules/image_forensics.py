
import io
import sys
from functools import lru_cache

from huggingface_hub import snapshot_download

from PIL import (
    Image,
    ImageChops,
    ImageEnhance,
    ImageFilter,
    ImageStat,
    ExifTags,
    UnidentifiedImageError
)


MODEL_NAME = "abacusai/Smaug-AI-Image-Detector"
DISPLAY_MODEL_NAME = "TruthLens AI Image Detector"
MODEL_PROVIDER = "Smaug-AI-Image-Detector by Abacus.AI"


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
    """Download once and cache the Smaug image detector."""
    model_path = snapshot_download(
        repo_id=MODEL_NAME,
        allow_patterns=[
            "modules.json",
            "config.json",
            "config_sentence_transformers.json",
            "sentence_bert_config.json",
            "processor_config.json",
            "model.safetensors",
            "1_Pooling/*",
            "2_Normalize/*",
            "3_Dense/*",
            "smaug_image_detect.py",
            "tokenizer.json",
            "tokenizer_config.json",
            "chat_template.jinja",
        ],
    )
    if model_path not in sys.path:
        sys.path.insert(0, model_path)

    from smaug_image_detect import SmaugImageDetect

    return SmaugImageDetect.from_pretrained(model_path)


def detect_ai_image(image):
    """
    Estimate AI-generation likelihood with the Smaug detector.

    This is a model score, not proof of image origin.
    """
    try:
        classifier = load_ai_classifier()
        raw_score = classifier(image.convert("RGB"))
        if hasattr(raw_score, "item"):
            raw_score = raw_score.item()
        ai_score = float(raw_score)

        if not 0.0 <= ai_score <= 1.0:
            raise ValueError("The image detector returned an invalid score.")

        human_score = 1.0 - ai_score
        prediction = (
            "Likely AI-generated"
            if ai_score >= 0.5
            else "Likely human-created"
        )

        return {
            "available": True,
            "prediction": prediction,
            "ai_score": round(ai_score * 100, 2),
            "human_score": round(human_score * 100, 2),
            "model": DISPLAY_MODEL_NAME,
            "engine": MODEL_PROVIDER,
            "warning": (
                "This is a probabilistic model estimate, not proof of image origin. "
                "Edited, compressed, cropped or newly generated images may be "
                "misclassified. Review the image and other evidence before drawing "
                "a conclusion."
            ),
        }

    except Exception as error:
        return {
            "available": False,
            "error": (
                "TruthLens AI image detector could not start or analyze this image: "
                + str(error)
            ),
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
            "TruthLens AI image detection is a probabilistic indicator, "
            "not proof of image origin."
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
