"""Consistent SQLite and private-asset backup/restore helpers for local recovery drills."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "recovery-manifest.json"
DATABASE_NAME = "axiomweave.sqlite3"
ASSETS_NAME = "private-assets"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Private asset path must be a real directory")
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Private asset snapshots cannot contain symbolic links")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": file_hash(path),
                }
            )
    return files


def _integrity_check(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise ValueError("SQLite integrity check failed")


def backup_sqlite(database_path: Path, asset_root: Path, backup_dir: Path) -> Path:
    source_db = database_path.expanduser().resolve()
    source_assets = asset_root.expanduser().resolve()
    destination = backup_dir.expanduser().resolve()
    if not source_db.is_file():
        raise ValueError("SQLite database file was not found")
    if destination.exists():
        raise ValueError("Backup destination already exists")
    destination.mkdir(parents=True)
    backup_db = destination / DATABASE_NAME
    try:
        with sqlite3.connect(source_db) as source, sqlite3.connect(backup_db) as target:
            source.backup(target)
        _integrity_check(backup_db)
        asset_files = _asset_manifest(source_assets)
        backup_assets = destination / ASSETS_NAME
        if source_assets.exists():
            shutil.copytree(source_assets, backup_assets, symlinks=False)
        for item in asset_files:
            if file_hash(backup_assets / item["path"]) != item["sha256"]:
                raise ValueError("Private asset checksum did not match after backup")
        manifest = {
            "format_version": 1,
            "database": {"path": DATABASE_NAME, "sha256": file_hash(backup_db)},
            "private_assets": asset_files,
        }
        (destination / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def restore_sqlite(backup_dir: Path, restore_dir: Path) -> Path:
    source = backup_dir.expanduser().resolve()
    destination = restore_dir.expanduser().resolve()
    if destination.exists():
        raise ValueError("Restore destination already exists; active data is never overwritten")
    manifest_path = source / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported recovery manifest version")
    database_info = manifest.get("database")
    if not isinstance(database_info, dict) or database_info.get("path") != DATABASE_NAME:
        raise ValueError("Recovery database entry is invalid")
    source_db = source / DATABASE_NAME
    if file_hash(source_db) != database_info.get("sha256"):
        raise ValueError("Recovery database checksum failed")
    asset_entries = manifest.get("private_assets")
    if not isinstance(asset_entries, list):
        raise ValueError("Recovery asset manifest is invalid")
    destination.mkdir(parents=True)
    try:
        restored_db = destination / DATABASE_NAME
        shutil.copy2(source_db, restored_db)
        _integrity_check(restored_db)
        restored_assets = destination / ASSETS_NAME
        restored_assets.mkdir()
        source_assets = source / ASSETS_NAME
        for item in asset_entries:
            if not isinstance(item, dict):
                raise ValueError("Recovery asset entry is invalid")
            relative = PurePosixPath(str(item.get("path", "")))
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError("Recovery asset path is invalid")
            source_file = source_assets.joinpath(*relative.parts)
            target_file = restored_assets.joinpath(*relative.parts)
            if file_hash(source_file) != item.get("sha256"):
                raise ValueError("Recovery asset checksum failed")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            if file_hash(target_file) != item.get("sha256"):
                raise ValueError("Restored asset checksum failed")
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("database", type=Path)
    backup_parser.add_argument("assets", type=Path)
    backup_parser.add_argument("destination", type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.operation == "backup":
        backup_sqlite(args.database, args.assets, args.destination)
    else:
        restore_sqlite(args.backup, args.destination)


if __name__ == "__main__":
    main()
