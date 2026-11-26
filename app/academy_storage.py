"""Explicitly configured private S3 client for future Academy upload services.

No network activity on import. No automatic credential discovery, bucket
creation, public ACL or signed URL generation. Enabling this client alone
does not enable any HTTP upload or download route.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Mapping
from urllib.parse import urlsplit


PREFIX = "STAZHNO_ACADEMY_"


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    region: str
    bucket: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)


def storage_config(env: Mapping[str, str] | None = None) -> StorageConfig | None:
    env = os.environ if env is None else env
    enabled = env.get(PREFIX + "STORAGE_ENABLED", "0").strip()
    if enabled == "0":
        return None
    if enabled != "1":
        raise RuntimeError("Invalid Academy storage enable flag")

    def required(name: str) -> str:
        value = env.get(PREFIX + "S3_" + name, "").strip()
        if not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise RuntimeError("Missing or invalid Academy S3 setting: " + name)
        return value

    endpoint = required("ENDPOINT")
    try:
        parsed = urlsplit(endpoint)
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None
                 and parsed.port in (None, 443) and parsed.path in ("", "/")
                 and not parsed.query and not parsed.fragment
                 and not any(ch.isspace() or ch == "\\" for ch in endpoint))
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("Academy S3 endpoint must be a plain HTTPS origin")

    bucket = required("BUCKET")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise RuntimeError("Invalid Academy S3 bucket name")
    region = required("REGION")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", region):
        raise RuntimeError("Invalid Academy S3 region")
    return StorageConfig(endpoint.rstrip("/"), region, bucket,
                         required("ACCESS_KEY"), required("SECRET_KEY"))


def build_storage_client(config: StorageConfig):
    """Construct the optional SDK only when explicitly called by a service."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=config.endpoint, region_name=config.region,
        aws_access_key_id=config.access_key, aws_secret_access_key=config.secret_key,
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=60,
                      retries={"total_max_attempts": 2, "mode": "standard"},
                      s3={"addressing_style": "path"}),
        verify=True,
    )


def image_upload_config(env: Mapping[str, str] | None = None) -> tuple[StorageConfig, str] | None:
    """A second explicit switch plus scanner configuration are required."""
    env = os.environ if env is None else env
    flag = env.get(PREFIX + "IMAGE_UPLOAD_ENABLED", "0").strip()
    if flag == "0":
        return None
    if flag != "1":
        raise RuntimeError("Invalid Academy image upload flag")
    config = storage_config(env)
    scanner_path = env.get(PREFIX + "CLAMD_SOCKET", "").strip()
    if config is None or not os.path.isabs(scanner_path) or "\x00" in scanner_path:
        raise RuntimeError("Private storage and local scanner must be configured")
    return config, scanner_path


def image_upload_ready() -> bool:
    try:
        return image_upload_config() is not None
    except RuntimeError:
        return False
