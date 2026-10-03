from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from typing import Any, cast

import pytest

from app import private_asset_storage
from app.private_asset_storage import (
    AssetStorageError,
    LocalPrivateAssetStore,
    S3PrivateAssetStore,
    get_private_asset_store,
)
from app.settings import get_settings


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def put_object(self, **kwargs: object) -> None:
        key = cast(str, kwargs["Key"])
        content = cast(bytes, kwargs["Body"])
        self.put_calls.append(kwargs)
        self.objects[key] = content

    def head_object(self, **kwargs: object) -> dict[str, object]:
        key = cast(str, kwargs["Key"])
        if key not in self.objects:
            raise KeyError(key)
        return {"ContentLength": len(self.objects[key])}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        key = cast(str, kwargs["Key"])
        if key not in self.objects:
            raise KeyError(key)
        return {"Body": PartialReadBody(self.objects[key])}

    def delete_object(self, **kwargs: object) -> None:
        key = cast(str, kwargs["Key"])
        self.deleted.append(key)
        self.objects.pop(key, None)


class PartialReadBody(BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        if size is not None and size >= 0:
            size = min(size, 3)
        return super().read(size)


def test_s3_store_read_and_delete_use_private_random_object_keys() -> None:
    client = FakeS3Client()
    store = S3PrivateAssetStore("private-assets", cast(Any, client))
    content = b"private content"

    stored = store.store(content)

    assert len(stored.storage_key) == 32
    assert stored.storage_key in client.objects
    assert stored.content_hash == sha256(content).hexdigest()
    assert stored.byte_size == len(content)
    assert client.put_calls == [
        {"Bucket": "private-assets", "Key": stored.storage_key, "Body": content}
    ]
    assert store.read(stored.storage_key) == content

    store.delete(stored.storage_key)

    assert client.deleted == [stored.storage_key]
    assert stored.storage_key not in client.objects


def test_s3_store_and_read_enforce_max_bytes() -> None:
    client = FakeS3Client()
    store = S3PrivateAssetStore("private-assets", cast(Any, client))

    with pytest.raises(AssetStorageError):
        store.store(b"too large", max_bytes=4)

    stored = store.store(b"too large", max_bytes=16)
    with pytest.raises(AssetStorageError):
        store.read(stored.storage_key, max_bytes=4)


def test_s3_read_maps_missing_objects_to_safe_storage_error() -> None:
    store = S3PrivateAssetStore("private-assets", cast(Any, FakeS3Client()))

    with pytest.raises(AssetStorageError) as error:
        store.read("a" * 32)

    assert str(error.value) == "Private source asset storage is unavailable."


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_s3_rejects_invalid_keys_before_client_access(operation: str) -> None:
    client = FakeS3Client()
    store = S3PrivateAssetStore("private-assets", cast(Any, client))

    with pytest.raises(AssetStorageError):
        if operation == "read":
            store.read("../not-a-storage-key")
        else:
            store.delete("../not-a-storage-key")

    assert not client.put_calls
    assert not client.deleted


def test_factory_keeps_local_storage_as_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIH_PRIVATE_ASSET_BACKEND", raising=False)
    monkeypatch.setenv("SIH_PRIVATE_ASSET_DIR", "local-assets")
    get_settings.cache_clear()

    try:
        assert isinstance(get_private_asset_store(), LocalPrivateAssetStore)
    finally:
        get_settings.cache_clear()


def test_factory_selects_s3_and_uses_standard_aws_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client()
    call: dict[str, object] = {}

    def make_client(service_name: str, **kwargs: object) -> FakeS3Client:
        call["service_name"] = service_name
        call.update(kwargs)
        return client

    monkeypatch.setenv("SIH_PRIVATE_ASSET_BACKEND", "s3")
    monkeypatch.setenv("SIH_S3_BUCKET", "private-assets")
    monkeypatch.setenv("SIH_S3_ENDPOINT", "https://storage.example.test")
    monkeypatch.setenv("SIH_S3_REGION", "auto")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setattr(private_asset_storage.boto3, "client", make_client)
    get_settings.cache_clear()

    try:
        store = get_private_asset_store()
    finally:
        get_settings.cache_clear()

    assert isinstance(store, S3PrivateAssetStore)
    assert call["service_name"] == "s3"
    assert call["endpoint_url"] == "https://storage.example.test"
    assert call["region_name"] == "auto"
    assert call["aws_access_key_id"] == "access-key"
    assert call["aws_secret_access_key"] == "secret-key"
    config = cast(Any, call["config"])
    assert config.connect_timeout == 3
    assert config.read_timeout == 10


@pytest.mark.parametrize(
    ("missing_name", "missing_value"),
    [
        ("SIH_S3_BUCKET", ""),
        ("SIH_S3_ENDPOINT", ""),
        ("SIH_S3_REGION", ""),
        ("AWS_ACCESS_KEY_ID", ""),
        ("AWS_SECRET_ACCESS_KEY", ""),
    ],
)
def test_factory_fails_safely_when_s3_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
    missing_value: str,
) -> None:
    monkeypatch.setenv("SIH_PRIVATE_ASSET_BACKEND", "s3")
    monkeypatch.setenv("SIH_S3_BUCKET", "private-assets")
    monkeypatch.setenv("SIH_S3_ENDPOINT", "https://storage.example.test")
    monkeypatch.setenv("SIH_S3_REGION", "auto")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setenv(missing_name, missing_value)
    get_settings.cache_clear()

    try:
        with pytest.raises(AssetStorageError) as error:
            get_private_asset_store()
    finally:
        get_settings.cache_clear()

    assert str(error.value) == "Private source asset storage is unavailable."
