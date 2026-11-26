"""Offline Academy conversion for a dedicated, isolated media worker.

Never invoke from the web process. Only hand a job whose original bytes have
already passed integrity and antivirus checks to this worker. The deployment
must isolate it from secrets, DB, other jobs and network access, with CPU,
memory, process and scratch-volume limits. This module is not an OS sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO
import json
import math
import os
import re
import subprocess  # nosec B404 - fixed trusted executables, offline worker
import zipfile
from xml.etree import ElementTree  # nosec B405 - DTD rejected before parsing

MiB = 1024 * 1024
MAX_PDF_PAGES = 30
MAX_PDF_PREVIEW_BYTES = 3 * MiB
MAX_PDF_TOTAL_BYTES = 60 * MiB
MAX_VIDEO_PIXELS = 1920 * 1080
MAX_PREVIEW_EDGE = 1600
INPUTS = {
    "audio/mpeg": ("mp3", 80 * MiB, 1800, 64 * MiB),
    "audio/wav": ("wav", 80 * MiB, 1800, 64 * MiB),
    "audio/mp4": ("mov", 80 * MiB, 1800, 64 * MiB),
    "video/mp4": ("mov", 300 * MiB, 900, 160 * MiB),
}


class ConversionRejected(ValueError):
    """Unsupported, malformed or out-of-policy input."""


class ConversionFailed(RuntimeError):
    """Tool failure or timeout. The original must remain inaccessible."""


@dataclass(frozen=True)
class Rendition:
    path: Path
    content_type: str
    byte_count: int
    duration: float | None = None
    page: int | None = None


@dataclass(frozen=True)
class Tools:
    ffmpeg: str = "/usr/bin/ffmpeg"
    ffprobe: str = "/usr/bin/ffprobe"
    pdfinfo: str = "/usr/bin/pdfinfo"
    pdftoppm: str = "/usr/bin/pdftoppm"
    soffice: str = "/usr/bin/soffice"


def _run(executable: str, args: list[str], work: Path, timeout: int,
         capture: Path | None = None) -> None:
    # No arguments derived from filenames or arbitrary user options. Files are
    # copied into a unique empty work directory with fixed names. The caller
    # must run this process inside an isolated no-network worker.
    if not Path(executable).is_absolute():
        raise ConversionFailed("Converter executable must be an absolute path")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": str(work)}
    try:
        if capture is None:
            subprocess.run(  # nosec B603 - no shell, fixed executable/arguments
                [executable, *args], cwd=work, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout, check=True,
            )
        else:
            with capture.open("wb") as output:
                subprocess.run(  # nosec B603 - no shell, fixed executable/arguments
                    [executable, *args], cwd=work, env=env, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.DEVNULL, timeout=timeout, check=True,
                )
    except (OSError, subprocess.SubprocessError):
        raise ConversionFailed("Offline media converter failed") from None


def _copy(source: BinaryIO, path: Path, limit: int) -> None:
    size = 0
    with path.open("xb") as output:
        while chunk := source.read(min(MiB, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise ConversionRejected("Input exceeds format limit")
            output.write(chunk)
    if not size:
        raise ConversionRejected("Input is empty")


def _small_text(path: Path, limit: int = 65536) -> str:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ConversionRejected("Converter metadata is too large")
    try:
        return data.decode("utf-8")
    except UnicodeError:
        raise ConversionRejected("Invalid converter metadata") from None


def _demux_options(demux: str) -> list[str]:
    result = ["-max_alloc", str(128 * MiB), "-protocol_whitelist", "file,pipe",
              "-max_streams", "4", "-f", demux]
    if demux == "mov":
        result += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    return result


def _probe(path: Path, demux: str, work: Path, tools: Tools) -> dict:
    report = work / "probe.json"
    _run(tools.ffprobe, ["-v", "error", *_demux_options(demux),
        "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,channels:stream_disposition=attached_pic",
        "-of", "json", str(path)], work, 30, report)
    try:
        metadata = json.loads(_small_text(report))
        if not isinstance(metadata, dict):
            raise ValueError
        return metadata
    except (ValueError, TypeError):
        raise ConversionRejected("Invalid media metadata") from None


def _check(metadata: dict, *, video: bool, duration_limit: int, normalized: bool = False) -> float:
    try:
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= duration_limit:
            raise ValueError
        streams = metadata["streams"]
        if not isinstance(streams, list) or not 1 <= len(streams) <= 2:
            raise ValueError
        audio = [s for s in streams if s["codec_type"] == "audio"]
        visuals = [s for s in streams if s["codec_type"] == "video"]
        if len(audio) > 1 or len(visuals) != int(video) or len(audio) + len(visuals) != len(streams):
            raise ValueError
        if not video and len(audio) != 1:
            raise ValueError
        for track in audio:
            if not 1 <= int(track["channels"]) <= (2 if normalized else 8):
                raise ValueError
            if normalized and track["codec_name"] != "aac":
                raise ValueError
        for track in visuals:
            width, height = int(track["width"]), int(track["height"])
            fps = Fraction(track["avg_frame_rate"])
            if (width < 2 or height < 2 or width > 1920 or height > 1920
                    or width * height > MAX_VIDEO_PIXELS or not 0 < fps <= 60
                    or track.get("disposition", {}).get("attached_pic", 0)):
                raise ValueError
            if normalized and (track["codec_name"] != "h264" or width > 1280 or height > 720):
                raise ValueError
        return duration
    except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        raise ConversionRejected("Media exceeds duration, track or resolution policy") from None


def normalize_av(source: BinaryIO, content_type: str, destination: Path, *, tools: Tools = Tools()) -> Rendition:
    """Produce a new MP4/AAC rendition. Original metadata/extra streams omitted.

    The destination must be a private, trusted empty job directory. Publish
    only after integrity/antivirus checks of the resulting rendition and
    durable registration, not merely because conversion returned.
    """
    rule = INPUTS.get(content_type)
    if rule is None:
        raise ConversionRejected("Unsupported audio/video format")
    demux, input_limit, duration_limit, output_limit = rule
    video = content_type == "video/mp4"
    destination = Path(destination).resolve(strict=True)
    target = destination / ("video.mp4" if video else "audio.m4a")
    if not destination.is_dir() or any(destination.iterdir()):
        raise ConversionFailed("Destination must be a private empty directory")
    with TemporaryDirectory(prefix="convert-", dir=destination) as temporary:
        work = Path(temporary)
        input_path = work / "source.bin"
        output = work / "result.mp4"
        _copy(source, input_path, input_limit)
        duration = _check(_probe(input_path, demux, work, tools),
                          video=video, duration_limit=duration_limit)
        args = ["-hide_banner", "-loglevel", "error", "-nostdin", "-xerror",
                "-filter_threads", "1", *_demux_options(demux),
                "-threads", "1", "-max_pixels", str(MAX_VIDEO_PIXELS),
                "-i", str(input_path)]
        if video:
            args += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                     "-preset", "fast", "-crf", "25", "-pix_fmt", "yuv420p",
                     "-vf", "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                     "-maxrate", "1100k", "-bufsize", "2200k"]
        else:
            args += ["-map", "0:a:0", "-vn"]
        args += ["-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "44100",
                 "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-threads", "1", "-t", str(duration_limit + 1),
                 "-fs", str(output_limit + 1), "-movflags", "+faststart",
                 "-f", "mp4", "-n", str(output)]
        _run(tools.ffmpeg, args, work, 300)
        size = output.stat().st_size
        if not 0 < size <= output_limit:
            raise ConversionRejected("Rendition exceeds output limit")
        result_duration = _check(_probe(output, "mov", work, tools), video=video,
                                 duration_limit=duration_limit + 1, normalized=True)
        # A capped, truncated or inconsistent file is not a successful result.
        if abs(result_duration - duration) > max(0.25, min(1.0, duration * 0.01)):
            raise ConversionRejected("Rendition duration differs from source")
        os.replace(output, target)
        return Rendition(target, "video/mp4" if video else "audio/mp4", size, result_duration)


def _pdf_pages(path: Path, work: Path, tools: Tools) -> int:
    report = work / "pdfinfo.txt"
    _run(tools.pdfinfo, [str(path)], work, 30, report)
    info = _small_text(report)
    pages = re.findall(r"^Pages:[ \t]+([0-9]+)[ \t]*$", info, re.MULTILINE)
    encrypted = re.findall(r"^Encrypted:[ \t]+([^\r\n]+)$", info, re.MULTILINE)
    if len(pages) != 1 or encrypted != ["no"]:
        raise ConversionRejected("Encrypted or invalid PDF")
    count = int(pages[0])
    if not 1 <= count <= MAX_PDF_PAGES:
        raise ConversionRejected("PDF page count exceeds limit")
    return count


def rasterize_pdf(source: BinaryIO, destination: Path, *, tools: Tools = Tools()) -> list[Rendition]:
    """Render each page to a new JPEG; never serve the original PDF inline."""
    from PIL import Image, ImageFile
    import warnings

    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ConversionFailed("Truncated image decoding is enabled")
    destination = Path(destination).resolve(strict=True)
    if not destination.is_dir() or any(destination.iterdir()):
        raise ConversionFailed("Destination must be a private empty directory")
    with TemporaryDirectory(prefix="pdf-", dir=destination) as temporary:
        work = Path(temporary)
        document = work / "source.pdf"
        _copy(source, document, 25 * MiB)
        with document.open("rb") as original:
            if original.read(5) != b"%PDF-":
                raise ConversionRejected("Expected a PDF")
        count = _pdf_pages(document, work, tools)
        pending = []
        total = 0
        for page in range(1, count + 1):
            prefix = work / "raster"
            _run(tools.pdftoppm, ["-f", str(page), "-l", str(page), "-singlefile",
                 "-scale-to", str(MAX_PREVIEW_EDGE), "-png", str(document), str(prefix)], work, 30)
            raster = prefix.with_suffix(".png")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(raster, formats=["PNG"]) as image:
                    if (max(image.size) > MAX_PREVIEW_EDGE or
                            image.width * image.height > MAX_PREVIEW_EDGE ** 2):
                        raise ConversionRejected("PDF raster exceeds image limit")
                    image.load()
                    rgb = Image.new("RGB", image.size, "white")
                    rgb.paste(image.convert("RGB"))
                    name = f"page-{page:03d}.jpg"
                    output = work / name
                    rgb.save(output, "JPEG", quality=85, optimize=True)
            raster.unlink()
            size = output.stat().st_size
            total += size
            if not 0 < size <= MAX_PDF_PREVIEW_BYTES or total > MAX_PDF_TOTAL_BYTES:
                raise ConversionRejected("PDF rendition exceeds storage limit")
            pending.append((output, Rendition(destination / name, "image/jpeg", size, page=page)))
        # Nothing appears at the final path until all pages have been rendered.
        committed = []
        try:
            for output, item in pending:
                os.replace(output, item.path)
                committed.append(item.path)
        except OSError:
            for path in committed:
                path.unlink(missing_ok=True)
            raise ConversionFailed("PDF output commit failed") from None
        return [item for _, item in pending]


def _xml_part(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as source:
        data = source.read(8 * MiB + 1)
    if len(data) > 8 * MiB:
        raise ConversionRejected("PPTX XML part exceeds limit")
    try:
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError
        # No XML declarations with alternate encodings are accepted.
        declaration = re.match(r'^<\?xml\s+[^?]*encoding\s*=\s*["\']([^"\']+)', text, re.I)
        if declaration and declaration.group(1).lower() not in ("utf-8", "utf8"):
            raise ValueError
        return ElementTree.fromstring(text)  # nosec B314 - DTD/entities prohibited, bounded local input
    except (UnicodeError, ValueError, ElementTree.ParseError):
        raise ConversionRejected("Unsupported PPTX XML") from None


def _validate_pptx(path: Path) -> None:
    """Conservative preflight before a separate isolated LibreOffice run."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 2000:
                raise ConversionRejected("PPTX archive entry limit exceeded")
            names = set()
            total = 0
            for entry in entries:
                name = entry.filename
                lower = name.casefold()
                parts = lower.rstrip("/").split("/")
                total += entry.file_size
                if (not name or "\\" in name or ":" in name
                        or any(ord(ch) < 32 for ch in name)
                        or any(part in ("", ".", "..") for part in parts)
                        or lower in names or entry.flag_bits & 1
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000
                        or total > 250 * MiB
                        or any(part in ("embeddings", "activex", "customui", "externallinks") for part in parts)
                        or lower.endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".vbs"))):
                    raise ConversionRejected("Unsupported or active PPTX archive content")
                names.add(lower)
            if not {"[content_types].xml", "ppt/presentation.xml", "_rels/.rels"} <= names:
                raise ConversionRejected("Incomplete PPTX package")
            for entry in entries:
                name = entry.filename
                if name == "[Content_Types].xml":
                    root = _xml_part(archive, name)
                    for item in root:
                        value = item.attrib.get("ContentType", "").lower()
                        if any(marker in value for marker in ("macroenabled", "vba", "activex", "oleobject", "externallink")):
                            raise ConversionRejected("Active PPTX content is not allowed")
                elif name.lower().endswith(".rels"):
                    root = _xml_part(archive, name)
                    for item in root:
                        mode = item.attrib.get("TargetMode", "Internal").lower()
                        target = item.attrib.get("Target", "")
                        kind = item.attrib.get("Type", "").rsplit("/", 1)[-1].lower()
                        if (mode != "internal" or not target or ":" in target or "\\" in target
                                or target.startswith("//")
                                or kind in ("oleobject", "package", "control", "vbaproject", "externallink")):
                            raise ConversionRejected("External links or embedded active objects are not allowed")
            root = _xml_part(archive, "ppt/presentation.xml")
            slides = root.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId")
            if not 1 <= len(slides) <= MAX_PDF_PAGES:
                raise ConversionRejected("PPTX slide count exceeds limit")
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        raise ConversionRejected("Invalid PPTX package") from None


def rasterize_pptx(source: BinaryIO, destination: Path, *, tools: Tools = Tools()) -> list[Rendition]:
    """Render static slides through an isolated LibreOffice profile then PDF."""
    destination = Path(destination).resolve(strict=True)
    if not destination.is_dir() or any(destination.iterdir()):
        raise ConversionFailed("Destination must be a private empty directory")
    # Use isolated scratch space so the PDF output directory is empty.
    # Both directories belong to the same isolated job.
    with TemporaryDirectory(prefix="presentation-") as temporary:
        work = Path(temporary)
        original = work / "source.pptx"
        _copy(source, original, 50 * MiB)
        _validate_pptx(original)
        profile = work / "lo-profile"
        profile.mkdir()
        user = profile / "user"
        user.mkdir()
        (user / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        _run(tools.soffice, ["-env:UserInstallation=" + profile.as_uri(),
             "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
             "--norestore", "--convert-to", "pdf:impress_pdf_Export",
             "--outdir", str(work), str(original)], work, 120)
        pdf = work / "source.pdf"
        if not pdf.is_file():
            raise ConversionFailed("PPTX converter did not produce a PDF")
        with pdf.open("rb") as stream:
            return rasterize_pdf(stream, destination, tools=tools)
