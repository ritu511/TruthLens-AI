import io
import sys
from functools import lru_cache

from PIL import (
    Image,
    ImageChops,
    ImageEnhance,
    ImageFilter,
    ImageStat,
    ExifTags,
    UnidentifiedImageError,
)


# Smaug is the selected open-source detector. Its model card documents an
# approximately 910 MB download on first use. Hugging Face caches the snapshot
# after download, so subsequent scans in the same deployment reuse it.
MODEL_NAME = "abacusai/Smaug-AI-Image-Detector"
AI_THRESHOLD = 0.50


def extract_image_metadata(image):
    """Extract basic image metadata and EXIF information."""

    metadata = {
        "format": image.format or "Unknown",
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "exif": {},
    }

    try:
        for tag_id, value in image.getexif().items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if not isinstance(value, bytes):
                metadata["exif"][tag_name] = str(value)
    except Exception:
        # EXIF data is optional and must not stop the image investigation.
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
        ),
    }


def generate_ela(image, quality=90):
    """Generate an Error Level Analysis visualization for JPEG files.

    ELA is a visual inspection aid only. Compression and normal edits can
    change ELA output, so it is not proof of manipulation.
    """

    if image.format != "JPEG":
        return None

    original = image.convert("RGB")
    buffer = io.BytesIO()
    original.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)

    with Image.open(buffer) as recompressed_image:
        recompressed = recompressed_image.convert("RGB")

    difference = ImageChops.difference(original, recompressed)
    statistics = ImageStat.Stat(difference)
    max_difference = max(max(channel) for channel in statistics.extrema)

    if max_difference > 0:
        difference = ImageEnhance.Brightness(difference).enhance(
            255.0 / max_difference
        )

    return difference


@lru_cache(maxsize=1)
def load_ai_classifier():
    """Download once, cache, and load the Smaug image detector.

    The model repository supplies SmaugImageDetect and its loading helper.
    The loader selects a supported device (CUDA, Apple Silicon Metal, or CPU).
    """

    from huggingface_hub import snapshot_download

    model_path = str(snapshot_download(repo_id=MODEL_NAME))

    # The detector's Python helper is shipped inside the model snapshot.
    if model_path not in sys.path:
        sys.path.insert(0, model_path)

    from smaug_image_detect import SmaugImageDetect

    return SmaugImageDetect.from_pretrained(model_path)


def detect_ai_image(image):
    """Return Smaug's AI-generated probability for a PIL image.

    The model returns a scalar score in [0, 1]. It is a model estimate, not
    proof or independently calibrated certainty about image provenance.
    """

    try:
        classifier = load_ai_classifier()
        raw_score = classifier(image.convert("RGB"))

        # The released API returns one scalar. Also accept scalar-like arrays
        # and one-item containers so wrappers do not break the integration.
        if isinstance(raw_score, (list, tuple)):
            if len(raw_score) != 1:
                raise ValueError("The detector returned an unexpected batch size.")
            raw_score = raw_score[0]
        if hasattr(raw_score, "item"):
            raw_score = raw_score.item()

        ai_probability = float(raw_score)
        if not 0.0 <= ai_probability <= 1.0:
            raise ValueError("The detector returned a score outside [0, 1].")

        ai_score = round(ai_probability * 100.0, 2)
        human_score = round((1.0 - ai_probability) * 100.0, 2)
        prediction = (
            "AI-generated indicators detected"
            if ai_probability >= AI_THRESHOLD
            else "Human-created indicators detected"
        )

        return {
            "available": True,
            "prediction": prediction,
            "ai_score": ai_score,
            "human_score": human_score,
            "confidence": round(
                max(ai_probability, 1.0 - ai_probability) * 100.0, 2
            ),
            "model": MODEL_NAME,
            "engine": "Smaug AI Image Detector (local model)",
            "warning": (
                "This is a model score, not proof of image origin. Edited, "
                "cropped, compressed, or newly generated images may be "
                "misclassified. Review the metadata and other evidence too."
            ),
        }

    except Exception as error:
        return {
            "available": False,
            "error": (
                "Smaug AI Image Detector could not be loaded or run. "
                "Check that sentence-transformers[image] is installed and "
                "the host has enough memory and disk space for the model. "
                f"Details: {error}"
            ),
        }


def analyze_image(image_bytes):
    """Main image-forensics function; keeps the existing app.py result shape."""

    try:
        if not isinstance(image_bytes, (bytes, bytearray)):
            raise ValueError("Invalid image file data.")
        if not image_bytes:
            raise ValueError("The uploaded image is empty.")

        with Image.open(io.BytesIO(image_bytes)) as source_image:
            source_image.load()
            original_format = source_image.format
            image = source_image.copy()
            image.format = original_format

        metadata = extract_image_metadata(image)
        quality = analyze_image_quality(image)
        ela_image = generate_ela(image)
        ai_detection = detect_ai_image(image)

        warnings = []
        if not metadata["exif"]:
            warnings.append("No EXIF metadata found. It may have been removed.")
        if ela_image is None:
            warnings.append("ELA is available only for JPEG images.")
        warnings.append(
            "AI detection is a model-based indicator and cannot prove image origin."
        )
        warnings.append(
            "Metadata, edge measurements and ELA are inspection clues, not proof of manipulation."
        )

        return {
            "success": True,
            "metadata": metadata,
            "quality": quality,
            "ela_available": ela_image is not None,
            "ela_image": ela_image,
            "ai_detection": ai_detection,
            "file_size_kb": round(len(image_bytes) / 1024, 2),
            "warnings": warnings,
        }

    except (UnidentifiedImageError, OSError):
        return {
            "success": False,
            "error": "The uploaded file is not a valid readable image.",
        }
    except Exception as error:
        return {"success": False, "error": str(error)}
