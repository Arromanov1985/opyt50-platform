"""High-confidence repository secret scan.

Designed for CI: catches credential formats that should never be committed while
avoiding broad entropy heuristics that create noisy false positives.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_classic_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b"),
    "github_fine_grained_token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b"),
    "gitlab_token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,255}\b"),
}

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".woff", ".woff2", ".ttf", ".eot", ".db", ".sqlite", ".sqlite3",
}
SKIP_PATHS = {".git", ".venv", "node_modules", "__pycache__"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
    )
    result = []
    for raw in output.decode("utf-8", errors="strict").split("\0"):
        if not raw:
            continue
        path = Path(raw)
        if any(part in SKIP_PATHS for part in path.parts):
            continue
        if path.suffix.casefold() in SKIP_SUFFIXES:
            continue
        result.append(path)
    return result


def scan() -> list[tuple[str, str, int]]:
    findings: list[tuple[str, str, int]] = []
    for relative in tracked_files():
        full = ROOT / relative
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((name, relative.as_posix(), line_no))
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Potential committed secrets detected:")
        for kind, path, line in findings:
            # Never print the matching line or credential value.
            print(f"- {kind}: {path}:{line}")
        return 2
    print("Secret scan: no high-confidence committed credentials detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
