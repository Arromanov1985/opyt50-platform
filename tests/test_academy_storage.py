"""No real credentials, bucket, network calls or optional SDK required."""
import sys
from types import SimpleNamespace

import pytest

from app.academy_storage import storage_config, build_storage_client


PREFIX = "STAZHNO_ACADEMY_"
SETTINGS = {
    PREFIX + "STORAGE_ENABLED": "1",
    PREFIX + "S3_ENDPOINT": "https://objects.example.invalid/",
    PREFIX + "S3_REGION": "ru-test",
    PREFIX + "S3_BUCKET": "private-academy-test",
    PREFIX + "S3_ACCESS_KEY": "dummy-access",
    PREFIX + "S3_SECRET_KEY": "dummy-secret",
}


def test_disabled_storage_does_not_require_credentials():
    assert storage_config({}) is None
    assert storage_config({PREFIX + "STORAGE_ENABLED": "0"}) is None


@pytest.mark.parametrize("field", ["ENDPOINT", "REGION", "BUCKET", "ACCESS_KEY", "SECRET_KEY"])
def test_enabled_storage_requires_all_settings(field):
    env = dict(SETTINGS)
    del env[PREFIX + "S3_" + field]
    with pytest.raises(RuntimeError, match=field):
        storage_config(env)


@pytest.mark.parametrize("endpoint", [
    "http://objects.example.invalid",
    "https://user:pass@objects.example.invalid",
    "https://objects.example.invalid/private",
    "https://objects.example.invalid/?key=secret",
    "https://objects.example.invalid/#fragment",
    "https://objects.example.invalid:1234",
])
def test_s3_configuration_rejects_insecure_or_ambiguous_endpoints(endpoint):
    with pytest.raises(RuntimeError, match="HTTPS origin"):
        storage_config({**SETTINGS, PREFIX + "S3_ENDPOINT": endpoint})


def test_client_configuration_uses_tls_and_explicit_credentials(monkeypatch):
    seen = {}
    sentinel = object()

    def client(service, **kwargs):
        seen.update(service=service, **kwargs)
        return sentinel

    def config(**kwargs):
        return kwargs

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=config))
    settings = storage_config(SETTINGS)
    assert "dummy-secret" not in repr(settings)
    assert "dummy-access" not in repr(settings)
    assert build_storage_client(settings) is sentinel
    assert seen["service"] == "s3" and seen["verify"] is True
    assert seen["endpoint_url"] == "https://objects.example.invalid"
    assert seen["aws_access_key_id"] == "dummy-access"
    assert seen["aws_secret_access_key"] == "dummy-secret"
    assert seen["config"]["signature_version"] == "s3v4"


def test_image_upload_has_independent_switch_and_local_scanner():
    from app.academy_storage import image_upload_config
    assert image_upload_config(SETTINGS) is None
    enabled = {**SETTINGS, PREFIX + "IMAGE_UPLOAD_ENABLED": "1"}
    with pytest.raises(RuntimeError):
        image_upload_config(enabled)
    enabled[PREFIX + "CLAMD_SOCKET"] = "/run/clamav/clamd.sock"
    config, path = image_upload_config(enabled)
    assert path == "/run/clamav/clamd.sock"
    assert config.bucket == "private-academy-test"
    with pytest.raises(RuntimeError):
        image_upload_config({**enabled, PREFIX + "STORAGE_ENABLED":"0"})
