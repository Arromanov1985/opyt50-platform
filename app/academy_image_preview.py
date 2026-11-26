"""Render a fresh, metadata-free preview from a verified quarantine image.

The original is never returned. This helper is only called after a clean
registered image is authorized for a specific private draft.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import time
import warnings

from .academy_media import MiB
from .academy_media_scan import ScanJob, _valid_job, CHUNK, MAX_IMAGE_PIXELS

MAX_PREVIEW_EDGE = 1600
MAX_PREVIEW_BYTES = 3 * MiB


def sanitized_preview(job: ScanJob, *, storage, private_bucket: str) -> bytes:
    from PIL import Image, ImageFile, ImageOps

    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}.get(job.content_type)
    if not expected or not _valid_job(job) or not private_bucket or ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError("Invalid preview source")
    deadline = time.monotonic() + 30
    response = storage.get_object(Bucket=private_bucket, Key=job.object_key)
    body = response["Body"]
    try:
        if response.get("ContentLength") != job.byte_count:
            raise ValueError("Image size mismatch")
        raw = BytesIO()
        digest = sha256()
        size = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Image read exceeded deadline")
            chunk = body.read(min(CHUNK, job.byte_count - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > job.byte_count:
                raise ValueError("Image size mismatch")
            raw.write(chunk)
            digest.update(chunk)
        if time.monotonic() >= deadline or size != job.byte_count or digest.hexdigest() != job.sha256:
            raise ValueError("Image integrity mismatch")
    finally:
        body.close()

    raw.seek(0)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(raw, formats=[expected]) as image:
            if (image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS
                    or getattr(image, "n_frames", 1) != 1):
                raise ValueError("Unsupported image")
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_PREVIEW_EDGE, MAX_PREVIEW_EDGE))
            # A newly allocated RGB canvas deliberately carries no EXIF,
            # XMP, ICC profiles, PNG comments or trailing source bytes.
            rgb = Image.new("RGB", image.size, "white")
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb.paste(image.convert("RGB"))
            output = BytesIO()
            rgb.save(output, format="JPEG", quality=82, optimize=True)
    data = output.getvalue()
    if len(data) > MAX_PREVIEW_BYTES:
        raise ValueError("Preview too large")
    return data
