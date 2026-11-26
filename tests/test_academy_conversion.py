"""Real codec/raster smoke tests run on the dedicated CI job, not the web host."""
from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import struct
import subprocess
import wave

import pytest
from PIL import Image
from app.academy_conversion import (
    ConversionRejected, ConversionFailed, Tools, normalize_av, rasterize_pdf, _check,
)


def test_conversion_policy_rejects_invalid_duration_and_tracks():
    valid = {"format":{"duration":"12.5"}, "streams":[{"codec_type":"audio","channels":1,"codec_name":"aac"}]}
    assert _check(valid, video=False, duration_limit=1800) == 12.5
    for duration in ("NaN", "inf", "0", "1801"):
        with pytest.raises(ConversionRejected):
            _check({**valid, "format":{"duration":duration}}, video=False, duration_limit=1800)
    with pytest.raises(ConversionRejected):
        _check({**valid, "streams":[*valid["streams"], {"codec_type":"attachment"}]},
               video=False, duration_limit=1800)


def test_conversion_never_uses_nonempty_output_or_unknown_mime(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(ConversionRejected):
        normalize_av(BytesIO(b"test"), "text/html", output)
    (output / "existing").write_bytes(b"keep")
    with pytest.raises(ConversionFailed):
        normalize_av(BytesIO(b"test"), "audio/wav", output)
    assert (output / "existing").read_bytes() == b"keep"


requires_tools = pytest.mark.skipif(os.getenv("STAZHNO_TEST_MEDIA_TOOLS") != "1",
                                    reason="Dedicated offline conversion CI job")


@requires_tools
def test_real_wav_is_normalized_to_aac(tmp_path):
    source = BytesIO()
    with wave.open(source, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(struct.pack("<h", 0) * 8000)
    source.seek(0)
    output = tmp_path / "audio"
    output.mkdir()
    item = normalize_av(source, "audio/wav", output)
    assert item.path.name == "audio.m4a"
    assert item.content_type == "audio/mp4"
    assert item.byte_count == item.path.stat().st_size
    assert 0.9 < item.duration < 1.25
    assert list(output.iterdir()) == [item.path]


@requires_tools
def test_real_mp4_is_normalized_without_source_metadata(tmp_path):
    source = tmp_path / "original.mp4"
    subprocess.run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=15:d=1",
        "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
        "-metadata", "comment=source-private-marker", "-y", str(source)], check=True, timeout=20)
    output = tmp_path / "video"
    output.mkdir()
    with source.open("rb") as stream:
        item = normalize_av(stream, "video/mp4", output)
    assert item.content_type == "video/mp4"
    assert 0.8 < item.duration < 1.25
    metadata = json.loads(subprocess.check_output(["/usr/bin/ffprobe", "-v", "error",
        "-show_format", "-of", "json", str(item.path)], timeout=20))
    assert "source-private-marker" not in json.dumps(metadata)
    assert b"source-private-marker" not in item.path.read_bytes()


@requires_tools
def test_real_pdf_is_rendered_to_ordered_jpeg_pages(tmp_path):
    source = BytesIO()
    Image.new("RGB", (400, 600), "white").save(source, format="PDF", save_all=True,
        append_images=[Image.new("RGB", (600, 400), "blue")])
    source.seek(0)
    output = tmp_path / "pdf"
    output.mkdir()
    items = rasterize_pdf(source, output)
    assert [item.page for item in items] == [1,2]
    assert [item.path.name for item in items] == ["page-001.jpg","page-002.jpg"]
    for item in items:
        with Image.open(item.path) as page:
            assert page.format == "JPEG"
            assert max(page.size) <= 1600
            assert not page.getexif()
    assert len(list(output.iterdir())) == 2


@requires_tools
def test_malformed_video_produces_no_final_output(tmp_path):
    with pytest.raises((ConversionRejected, ConversionFailed)):
        normalize_av(BytesIO(b"not a video"), "video/mp4", tmp_path)
    assert not list(tmp_path.iterdir())
