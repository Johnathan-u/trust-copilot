"""MinIO/S3 object storage client (FILE-01)."""

import io
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings


class StorageClient:
    """Reusable interface for MinIO/S3 operations."""

    def __init__(self):
        settings = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"),
            use_ssl=settings.s3_use_ssl,
            region_name="us-east-1",
        )
        self._bucket_raw = settings.s3_bucket_raw
        self._bucket_exports = settings.s3_bucket_exports

    def ping(self) -> None:
        """Verify S3/MinIO connectivity. Raises on failure."""
        self._client.list_buckets()

    def ensure_buckets(self) -> None:
        """Create buckets if they do not exist."""
        for bucket in [self._bucket_raw, self._bucket_exports]:
            try:
                self._client.head_bucket(Bucket=bucket)
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    self._client.create_bucket(Bucket=bucket)
                else:
                    raise

    def upload(
        self,
        bucket: str,
        key: str,
        body: bytes | BinaryIO,
        content_type: str | None = None,
    ) -> str:
        """Upload object, return key."""
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
        return key

    def download(self, bucket: str, key: str) -> bytes:
        """Download object as bytes."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def download_stream(self, bucket: str, key: str) -> BinaryIO:
        """Download object as stream."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"]

    def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        self._client.delete_object(Bucket=bucket, Key=key)

    def exists(self, bucket: str, key: str) -> bool:
        """Check if object exists."""
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    def get_presigned_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate presigned GET URL."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    @property
    def bucket_raw(self) -> str:
        return self._bucket_raw

    @property
    def bucket_exports(self) -> str:
        return self._bucket_exports


def get_storage() -> StorageClient:
    """Dependency for FastAPI routes."""
    return StorageClient()
