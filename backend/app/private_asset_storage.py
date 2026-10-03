"""Private, application-owned storage for bounded source upload bytes."""

import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

MAX_PRIVATE_ASSET_BYTES = 8 * 1024 * 1024
MAX_RENDERED_MEDIA_BYTES = 256 * 1024 * 1024
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}$")


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


def get_private_asset_store() -> PrivateAssetStore:
    from app.settings import get_settings

    return LocalPrivateAssetStore(get_settings().private_asset_dir)
