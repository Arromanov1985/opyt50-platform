"""One-job command for the dedicated offline converter container."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from app.academy_conversion import INPUTS, normalize_av, rasterize_pdf, rasterize_pptx

DOCUMENTS = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-type", required=True, choices=tuple(INPUTS) + DOCUMENTS)
    args = parser.parse_args()
    original = Path("/input/source")
    destination = Path("/output")
    try:
        with original.open("rb") as source:
            if args.content_type in INPUTS:
                items = [normalize_av(source, args.content_type, destination)]
            elif args.content_type == "application/pdf":
                items = rasterize_pdf(source, destination)
            else:
                items = rasterize_pptx(source, destination)
        report = []
        for item in items:
            with item.path.open("rb") as stream:
                digest = sha256()
                while chunk := stream.read(65536):
                    digest.update(chunk)
            report.append({"name":item.path.name, "content_type":item.content_type,
                           "byte_count":item.byte_count, "sha256":digest.hexdigest(),
                           "duration":item.duration, "page":item.page})
        # A trusted parent validates this manifest, rechecks hashes and scans
        # the derivatives before any private storage or database registration.
        print(json.dumps({"renditions":report}, separators=(",", ":")))
        return 0
    except Exception:
        # No raw content, external tool diagnostics or user metadata in logs.
        print(json.dumps({"error":"conversion_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
