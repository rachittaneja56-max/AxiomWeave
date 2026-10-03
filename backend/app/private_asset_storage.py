"""Private, application-owned storage for bounded source upload bytes."""

import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

import boto3  # pyright: ignore[reportMissingTypeStubs]
from botocore.config import Config  # pyright: ignore[reportMissingTypeStubs]

MAX_PRIVATE_ASSET_BYTES = 8 * 1024 * 1024
MAX_RENDERED_MEDIA_BYTES = 256 * 1024 * 1024
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}$")
_S3_CLIENT_CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
    s3={"addressing_style": "virtual"},
)


class AssetStorageError(OSError):
    """Safe storage error that does not expose local filesystem details."""

    def __init__(self) -> None:
        super().__init__("Private source asset storage is unavailable.")


@dataclass(frozen=True, slots=True)
class StoredPrivateAsset:
    storage_key: str
    content_hash: str
    byte_size: int


class PrivateAssetStore(Protocol):
    def store(
        self, content: bytes, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES
    ) -> StoredPrivateAsset: ...

    def read(self, storage_key: str, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...


class _S3Client(Protocol):
    def put_object(self, **kwargs: object) -> object: ...

    def head_object(self, **kwargs: object) -> dict[str, object]: ...

    def get_object(self, **kwargs: object) -> dict[str, object]: ...

    def delete_object(self, **kwargs: object) -> object: ...


class _S3ResponseBody(Protocol):
    def read(self, amt: int = -1) -> bytes: ...

    def close(self) -> None: ...


class LocalPrivateAssetStore:
    """Store objects under random keys in a non-public application directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def store(
        self, content: bytes, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES
    ) -> StoredPrivateAsset:
        if max_bytes <= 0 or max_bytes > MAX_RENDERED_MEDIA_BYTES or len(content) > max_bytes:
            raise AssetStorageError()
        storage_key = uuid4().hex
        directory = self.root / storage_key[:2]
        target = directory / storage_key
        target_created = False
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._restrict_directory(self.root)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not directory.resolve().is_relative_to(self.root):
                raise AssetStorageError()
            self._restrict_directory(directory)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            target_created = True
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            if target_created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            raise AssetStorageError() from None
        return StoredPrivateAsset(storage_key, sha256(content).hexdigest(), len(content))

    def read(self, storage_key: str, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES) -> bytes:
        target = self._path_for(storage_key)
        try:
            if target.is_symlink() or not target.is_file():
                raise AssetStorageError()
            content = target.read_bytes()
        except OSError:
            raise AssetStorageError() from None
        if max_bytes <= 0 or max_bytes > MAX_RENDERED_MEDIA_BYTES or len(content) > max_bytes:
            raise AssetStorageError()
        return content

    def delete(self, storage_key: str) -> None:
        target = self._path_for(storage_key)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            raise AssetStorageError() from None

    def _path_for(self, storage_key: str) -> Path:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise AssetStorageError()
        directory = self.root / storage_key[:2]
        try:
            resolved_directory = directory.resolve(strict=True)
        except OSError:
            raise AssetStorageError() from None
        if not resolved_directory.is_relative_to(self.root):
            raise AssetStorageError()
        return resolved_directory / storage_key

    @staticmethod
    def _restrict_directory(directory: Path) -> None:
        if os.name != "nt":
            directory.chmod(0o700)


class S3PrivateAssetStore:
    """Store private objects in an S3-compatible bucket under random keys."""

    def __init__(self, bucket: str, client: _S3Client) -> None:
        self.bucket = bucket
        self.client = client

    def store(
        self, content: bytes, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES
    ) -> StoredPrivateAsset:
        if max_bytes <= 0 or max_bytes > MAX_RENDERED_MEDIA_BYTES or len(content) > max_bytes:
            raise AssetStorageError()
        storage_key = uuid4().hex
        try:
            self.client.put_object(Bucket=self.bucket, Key=storage_key, Body=content)
        except Exception:
            raise AssetStorageError() from None
        return StoredPrivateAsset(storage_key, sha256(content).hexdigest(), len(content))

    def read(self, storage_key: str, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES) -> bytes:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise AssetStorageError()
        if max_bytes <= 0 or max_bytes > MAX_RENDERED_MEDIA_BYTES:
            raise AssetStorageError()
        try:
            metadata = self.client.head_object(Bucket=self.bucket, Key=storage_key)
            content_length = metadata.get("ContentLength")
            if (
                not isinstance(content_length, int)
                or content_length < 0
                or content_length > max_bytes
            ):
                raise AssetStorageError()
            response = self.client.get_object(Bucket=self.bucket, Key=storage_key)
            body = cast(_S3ResponseBody, response["Body"])
            content = bytearray()
            try:
                while len(content) <= max_bytes:
                    chunk = body.read(min(64 * 1024, max_bytes + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
            finally:
                body.close()
            if len(content) > max_bytes:
                raise AssetStorageError()
            return bytes(content)
        except AssetStorageError:
            raise
        except Exception:
            raise AssetStorageError() from None

    def delete(self, storage_key: str) -> None:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise AssetStorageError()
        try:
            self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        except Exception:
            raise AssetStorageError() from None


def get_private_asset_store() -> PrivateAssetStore:
    from app.settings import get_settings

    settings = get_settings()
    backend = settings.private_asset_backend.strip().lower()
    if backend == "local":
        return LocalPrivateAssetStore(settings.private_asset_dir)
    if backend == "s3":
        bucket = settings.s3_bucket
        endpoint = settings.s3_endpoint
        region = settings.s3_region
        access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if (
            not bucket
            or not bucket.strip()
            or not endpoint
            or not endpoint.strip()
            or not region
            or not region.strip()
            or not access_key_id
            or not access_key_id.strip()
            or not secret_access_key
            or not secret_access_key.strip()
        ):
            raise AssetStorageError()
        try:
            client = cast(Any, boto3).client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=_S3_CLIENT_CONFIG,
            )
        except Exception:
            raise AssetStorageError() from None
        return S3PrivateAssetStore(bucket, cast(_S3Client, client))
    raise AssetStorageError()


def private_asset_store_is_configured() -> bool:
    """Return whether the selected backend has the settings needed to use it."""
    from app.settings import get_settings

    settings = get_settings()
    backend = settings.private_asset_backend.strip().lower()
    if backend == "local":
        return True
    if backend != "s3":
        return False
    return all(
        value and value.strip()
        for value in (
            settings.s3_bucket,
            settings.s3_endpoint,
            settings.s3_region,
            os.environ.get("AWS_ACCESS_KEY_ID"),
            os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    )
