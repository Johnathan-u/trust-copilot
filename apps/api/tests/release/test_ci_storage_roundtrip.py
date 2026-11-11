"""Real upload, download and delete through StorageClient.

Other tests keep their in-memory fakes. This one talks to the disposable
S3-compatible service CI starts (motoserver/moto, Apache-2.0). A skip is a
failure when TC_REQUIRE_STORAGE=1.
"""

import os
import socket
import uuid
from urllib.parse import urlparse

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.storage]

_BODY = b"tc-02-007 synthetic storage round-trip"


def _endpoint_accepts_connections() -> bool:
    parsed = urlparse(os.environ.get("S3_ENDPOINT", ""))
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def test_storage_client_uploads_downloads_and_deletes():
    if not _endpoint_accepts_connections():
        if os.environ.get("TC_REQUIRE_STORAGE") == "1":
            pytest.fail("TC_REQUIRE_STORAGE=1: object storage unavailable")
        pytest.skip("object storage unavailable")
    from app.core.config import get_settings
    from app.services.storage import StorageClient

    get_settings.cache_clear()
    client = StorageClient()
    bucket = client.bucket_raw
    assert bucket == "test-raw"
    key = f"tc-02-007/{uuid.uuid4().hex}"
    assert client.upload(bucket, key, _BODY, content_type="application/octet-stream") == key
    try:
        assert client.download(bucket, key) == _BODY
    finally:
        client.delete(bucket, key)
    assert client.exists(bucket, key) is False
