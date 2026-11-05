"""TC-01-003: production object storage is an external S3 service, so the signing region is
configurable (S3_REGION, default us-east-1). Builds the boto3 client only; no network."""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "value,expected",
    [(None, "us-east-1"), ("", "us-east-1"), (" eu-central-1 ", "eu-central-1"), ("auto", "auto")],
)
def test_storage_client_uses_configured_region(monkeypatch, fresh_settings, value, expected):
    if value is None:
        monkeypatch.delenv("S3_REGION", raising=False)
    else:
        monkeypatch.setenv("S3_REGION", value)
    monkeypatch.setenv("S3_ACCESS_KEY", "synthetic-access-key")
    monkeypatch.setenv("S3_SECRET_KEY", "synthetic-secret-key-0123456789")
    from app.services.storage import StorageClient

    assert get_settings().s3_region == expected
    assert StorageClient()._client.meta.region_name == expected
