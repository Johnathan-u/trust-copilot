"""S3-compatible object storage client (FILE-01). MinIO in dev compose; external S3 in production."""

import io  # noqa: F401
import json
import logging
import os
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.config_contract import S3_PRIVACY_ATTESTATION_VALUE

logger = logging.getLogger(__name__)


class BucketNotPrivate(RuntimeError):
    """The object bucket is public, or production could not prove it is private."""


class PrivacyAttestationRejected(RuntimeError):
    """S3_PRIVACY_ATTESTATION is set to a value other than the one accepted value."""


_SKIPPED = object()


# Group URIs that grant the bucket to anyone, or to any signed-in AWS account.
_PUBLIC_GRANTEE_URIS = frozenset(
    {
        "http://acs.amazonaws.com/groups/global/allusers",
        "http://acs.amazonaws.com/groups/global/authenticatedusers",
    }
)
_MISSING_BUCKET = frozenset({"404", "nosuchbucket", "notfound"})
_MISSING_POLICY = frozenset({"nosuchbucketpolicy", "404"})
_MISSING_BLOCK = frozenset({"nosuchpublicaccessblockconfiguration", "404"})
_UNSUPPORTED = frozenset(
    {"notimplemented", "unsupportedoperation", "methodnotallowed", "notsupported", "501"}
)
_BLOCK_FLAGS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
_NOT_PRIVATE = "Object storage bucket is not private"
_UNCONFIRMED = "Object storage bucket privacy could not be confirmed"


def _error_code(exc: ClientError) -> str:
    error = exc.response.get("Error") if isinstance(exc.response, dict) else None
    if not isinstance(error, dict):
        return ""
    return str(error.get("Code") or "").strip().lower()


def _principal_is_public(principal: object) -> bool:
    if principal == "*":
        return True
    if isinstance(principal, list):
        return any(_principal_is_public(item) for item in principal)
    if not isinstance(principal, dict):
        return False
    for value in principal.values():
        if value == "*":
            return True
        if isinstance(value, list) and any(item == "*" for item in value):
            return True
    return False


def _policy_allows_public(raw: object) -> bool:
    """True when the policy grants any action to a public principal, or cannot be read."""
    if not isinstance(raw, str) or not raw.strip():
        return True
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return True
    if not isinstance(document, dict):
        return True
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        return True
    for statement in statements:
        if not isinstance(statement, dict):
            return True
        effect = str(statement.get("Effect") or "Allow").strip().lower()
        if effect != "allow":
            continue
        if _principal_is_public(statement.get("Principal")):
            return True
    return False


def _acl_is_public(acl: object) -> bool:
    if not isinstance(acl, dict):
        return True
    grants = acl.get("Grants")
    if not isinstance(grants, list):
        return True
    for grant in grants:
        if not isinstance(grant, dict):
            return True
        grantee = grant.get("Grantee")
        if not isinstance(grantee, dict):
            return True
        uri = str(grantee.get("URI") or "").strip().lower()
        if uri in _PUBLIC_GRANTEE_URIS:
            return True
    return False


def privacy_attestation_skips_unsupported() -> bool:
    """True only for the one accepted attestation. Any other non-empty value is refused.

    Unset keeps today's production behaviour: an unsupported privacy call fails closed.
    """
    value = os.getenv("S3_PRIVACY_ATTESTATION", "").strip()
    if not value:
        return False
    if value != S3_PRIVACY_ATTESTATION_VALUE:
        raise PrivacyAttestationRejected(
            "S3_PRIVACY_ATTESTATION must be unset or unsupported-store-private"
        )
    return True


def _warn_skipped(bucket: str, check: str) -> None:
    """One warning per skipped check. The text names the bucket and the check only."""
    logger.warning(
        "object storage privacy check skipped bucket=%s check=%s",
        bucket,
        check,
    )


def _block_is_complete(config: object) -> bool:
    if not isinstance(config, dict):
        return False
    return all(config.get(flag) is True for flag in _BLOCK_FLAGS)


class StorageClient:
    """Reusable interface for S3-compatible object storage operations."""

    def __init__(self):
        settings = get_settings()
        if not settings.s3_access_key or not settings.s3_secret_key:
            # TC-07-001: no literal fallback credentials, and never fall through to boto3's
            # ambient credential chain (instance profile, ~/.aws) by passing None.
            raise RuntimeError("S3_ACCESS_KEY and S3_SECRET_KEY must be set (see .env.example).")
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"),
            use_ssl=settings.s3_use_ssl,
            region_name=settings.s3_region,
        )
        self._bucket_raw = settings.s3_bucket_raw
        self._bucket_exports = settings.s3_bucket_exports

    def ping(self) -> None:
        """Verify S3/MinIO connectivity. Raises on failure."""
        self._client.list_buckets()

    def ensure_buckets(self) -> None:
        """Create a missing bucket as private, and refuse a bucket that is public.

        An existing bucket is checked and not rewritten. Production requires a
        full public-access block when the store can answer. An unsupported ACL,
        policy, or public-access-block call fails closed unless
        S3_PRIVACY_ATTESTATION is unsupported-store-private, which skips only
        that call. A supported call that shows public access still fails. The
        error and the skip warning do not include a policy or an ACL.
        """
        from app.core.session import is_production_env

        attested = privacy_attestation_skips_unsupported()
        production = is_production_env()
        for bucket in (self._bucket_raw, self._bucket_exports):
            self._ensure_one_bucket(bucket, production=production, attested=attested)

    def _ensure_one_bucket(self, bucket: str, *, production: bool, attested: bool) -> None:
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if _error_code(exc) not in _MISSING_BUCKET:
                if production:
                    raise BucketNotPrivate(_UNCONFIRMED) from exc
                raise
            self._client.create_bucket(Bucket=bucket)
            self._apply_private_defaults(bucket, production=production)
        self._require_private(bucket, production=production, attested=attested)

    def _apply_private_defaults(self, bucket: str, *, production: bool) -> None:
        self._client.put_bucket_acl(Bucket=bucket, ACL="private")
        try:
            self._client.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={flag: True for flag in _BLOCK_FLAGS},
            )
        except ClientError as exc:
            if production or _error_code(exc) not in _UNSUPPORTED:
                if production:
                    raise BucketNotPrivate(_UNCONFIRMED) from exc
                raise

    def _require_private(self, bucket: str, *, production: bool, attested: bool) -> None:
        try:
            acl = self._read_acl(bucket, production=production, attested=attested)
            public_policy = self._policy_is_public(bucket, production=production, attested=attested)
            block = self._public_access_block(bucket, production=production, attested=attested)
        except BucketNotPrivate:
            raise
        except ClientError as exc:
            if production:
                raise BucketNotPrivate(_UNCONFIRMED) from exc
            raise
        if acl is not _SKIPPED and _acl_is_public(acl):
            raise BucketNotPrivate(_NOT_PRIVATE)
        if public_policy is not _SKIPPED and public_policy:
            raise BucketNotPrivate(_NOT_PRIVATE)
        if production and block is not _SKIPPED and block is not True:
            raise BucketNotPrivate(_NOT_PRIVATE)

    def _read_acl(self, bucket: str, *, production: bool, attested: bool):
        try:
            return self._client.get_bucket_acl(Bucket=bucket)
        except ClientError as exc:
            if _error_code(exc) not in _UNSUPPORTED:
                raise
            if production and attested:
                _warn_skipped(bucket, "acl")
                return _SKIPPED
            if production:
                raise BucketNotPrivate(_UNCONFIRMED) from exc
            raise

    def _policy_is_public(self, bucket: str, *, production: bool, attested: bool):
        try:
            raw = self._client.get_bucket_policy(Bucket=bucket).get("Policy")
        except ClientError as exc:
            code = _error_code(exc)
            if code in _MISSING_POLICY:
                return False
            if code in _UNSUPPORTED and production and attested:
                _warn_skipped(bucket, "policy")
                return _SKIPPED
            if code in _UNSUPPORTED and not production:
                return False
            if production:
                raise BucketNotPrivate(_UNCONFIRMED) from exc
            raise
        return _policy_allows_public(raw)

    def _public_access_block(self, bucket: str, *, production: bool, attested: bool):
        try:
            payload = self._client.get_public_access_block(Bucket=bucket)
        except ClientError as exc:
            code = _error_code(exc)
            if code in _MISSING_BLOCK:
                return None
            if code in _UNSUPPORTED and production and attested:
                _warn_skipped(bucket, "public-access-block")
                return _SKIPPED
            if code in _UNSUPPORTED and not production:
                return None
            if production:
                raise BucketNotPrivate(_UNCONFIRMED) from exc
            raise
        if not isinstance(payload, dict):
            return False
        return _block_is_complete(payload.get("PublicAccessBlockConfiguration"))

    def upload(
        self,
        bucket: str,
        key: str,
        body: bytes | BinaryIO,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload object, return key.

        ``metadata`` is the checksum record (hash, version, media type, workspace).
        Callers that do not pass it leave the object unmarked.
        """
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = {str(name): str(value) for name, value in metadata.items()}
        self._client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
        return key

    def download(self, bucket: str, key: str) -> bytes:
        """Download object as bytes."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def download_checksummed(self, bucket: str, key: str) -> tuple[bytes, dict[str, str]]:
        """Download bytes plus the checksum metadata and the stored content type.

        User-metadata names come back lowercased. ``content-type`` is the
        object's content type, not a user-metadata field.
        """
        resp = self._client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read()
        meta: dict[str, str] = {}
        for name, value in (resp.get("Metadata") or {}).items():
            if isinstance(name, str) and isinstance(value, str):
                meta[name.lower()] = value
        content_type = resp.get("ContentType")
        if isinstance(content_type, str) and content_type:
            meta["content-type"] = content_type
        return body, meta

    def download_stream(self, bucket: str, key: str) -> BinaryIO:
        """Download object as stream."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"]

    def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        self._client.delete_object(Bucket=bucket, Key=key)

    def list_objects(self, bucket: str) -> list[dict]:
        """List every object in ``bucket``.

        Each item is ``{"key", "last_modified"}``. ``last_modified`` is the object store's clock
        (``LastModified``), or None when the store did not send one. Callers use it to tell an
        in-flight upload from an orphan. This does not add a database column.
        """
        paginator = self._client.get_paginator("list_objects_v2")
        found: list[dict] = []
        for page in paginator.paginate(Bucket=bucket):
            for item in page.get("Contents") or []:
                key = item.get("Key")
                if not key:
                    continue
                found.append({"key": key, "last_modified": item.get("LastModified")})
        return found

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
