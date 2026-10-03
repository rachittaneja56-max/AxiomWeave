import sqlite3
from pathlib import Path

import pytest

from scripts.sqlite_recovery import backup_sqlite, file_hash, restore_sqlite


def test_sqlite_and_private_assets_backup_restore_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "live.sqlite3"
    assets = tmp_path / "private-assets"
    assets.mkdir()
    (assets / "source").mkdir()
    (assets / "source" / "original.bin").write_bytes(b"private source bytes")
    (assets / "render.mp4").write_bytes(b"private rendered bytes")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE source_assets (storage_key TEXT NOT NULL)")
        connection.execute("INSERT INTO source_assets VALUES ('source/original.bin')")
        connection.execute("CREATE TABLE media_assets (storage_key TEXT NOT NULL)")
        connection.execute("INSERT INTO media_assets VALUES ('render.mp4')")

    backup = backup_sqlite(database, assets, tmp_path / "backup")
    restored = restore_sqlite(backup, tmp_path / "restored")

    with sqlite3.connect(restored / "axiomweave.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT storage_key FROM source_assets").fetchone() == (
            "source/original.bin",
        )
        assert connection.execute("SELECT storage_key FROM media_assets").fetchone() == (
            "render.mp4",
        )
    assert file_hash(assets / "source" / "original.bin") == file_hash(
        restored / "private-assets" / "source" / "original.bin"
    )
    assert file_hash(assets / "render.mp4") == file_hash(restored / "private-assets" / "render.mp4")
    with pytest.raises(ValueError, match="already exists"):
        restore_sqlite(backup, restored)


def test_restore_rejects_corrupt_backup_without_leaving_partial_destination(
    tmp_path: Path,
) -> None:
    database = tmp_path / "live.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE saved (value TEXT NOT NULL)")
        connection.execute("INSERT INTO saved VALUES ('kept')")
    backup = backup_sqlite(database, tmp_path / "missing-assets", tmp_path / "backup")
    (backup / "axiomweave.sqlite3").write_bytes(b"not a sqlite database")

    destination = tmp_path / "failed-restore"
    with pytest.raises(ValueError, match="checksum"):
        restore_sqlite(backup, destination)
    assert not destination.exists()
