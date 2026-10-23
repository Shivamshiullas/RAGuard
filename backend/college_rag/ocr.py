"""Image validation and OCR with RapidOCR (one preprocess-and-retry pass)."""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from . import faults
from .config import get_settings

log = logging.getLogger(__name__)

ALLOWED_IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
MIN_SIDE_PX = 16
MAX_SIDE_PX = 10_000


class ImageRejected(ValueError):
    """User-facing reason why an image cannot be processed."""


@dataclass
class OcrResult:
    text: str
    usable: bool
    attempts: int
    preprocessed: bool


_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def validate_image(data: bytes) -> tuple[Image.Image, str]:
    """Check size, format, integrity and dimensions. Returns (image, mime)."""
    settings = get_settings()
    if not data:
        raise ImageRejected("The image is empty.")
    if len(data) > settings.max_image_mb * 1024 * 1024:
        raise ImageRejected(f"The image is larger than {settings.max_image_mb} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ImageRejected("The file is not a readable PNG or JPG image.") from None
    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise ImageRejected("Only PNG and JPG images are supported.")
    image = Image.open(io.BytesIO(data))
    w, h = image.size
    if min(w, h) < MIN_SIDE_PX or max(w, h) > MAX_SIDE_PX or w * h > settings.max_image_pixels:
        raise ImageRejected("The image dimensions are too small or too large to read.")
    image.load()
    return image, ALLOWED_IMAGE_FORMATS[fmt]


def _run_ocr(image: Image.Image) -> str:
    faults.check("ocr")
    import numpy as np

    result, _ = _get_engine()(np.array(image.convert("RGB")))
    if not result:
        return ""
    return "\n".join(line[1] for line in result if line and len(line) > 1 and line[1])


def _preprocess(image: Image.Image) -> Image.Image:
    """Grayscale, auto-contrast and upscale small images (or shrink huge ones)."""
    img = ImageOps.autocontrast(ImageOps.grayscale(image))
    w, h = img.size
    longest = max(w, h)
    if longest < 1600:
        scale = 1600 / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    elif longest > 4000:
        scale = 4000 / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def is_usable(text: str) -> bool:
    letters = sum(ch.isalnum() for ch in text)
    return letters >= get_settings().min_ocr_chars


def ocr_image(image: Image.Image) -> OcrResult:
    """OCR once; if that fails or reads too little, preprocess and retry once.
    Raises the last error only if both attempts raised."""
    first_text, first_error = "", None
    try:
        first_text = _run_ocr(image)
        if is_usable(first_text):
            return OcrResult(first_text, True, 1, False)
    except Exception as exc:  # noqa: BLE001
        first_error = exc
        log.warning("OCR attempt 1 failed: %s", exc)

    try:
        second_text = _run_ocr(_preprocess(image))
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR attempt 2 failed: %s", exc)
        if first_error is not None:
            raise
        return OcrResult(first_text, False, 2, True)
    best = second_text if len(second_text) >= len(first_text) else first_text
    return OcrResult(best, is_usable(best), 2, True)
