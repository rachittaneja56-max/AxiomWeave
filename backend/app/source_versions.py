import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.transformation import SOURCE_TEXT_MAX_LENGTH
from app.models import (
    Source,
    SourceAsset,
    SourcePack,
    SourcePackVersion,
    SourceRegion,
    SourceSegment,
    SourceVersion,
    source_content_hash,
    utc_now,
)
from app.private_asset_storage import PrivateAssetStore, get_private_asset_store

AuthorityRole = Literal["authoritative", "supporting"]
SourceKind = Literal["text", "file", "url"]


@dataclass(frozen=True, slots=True)
class SourceAssetInput:
    source_kind: SourceKind = "text"
    media_type: str = "text/plain"
    original_filename: str | None = None
    raw_bytes: bytes | None = None
    provenance_url: str | None = None
    extraction_method: str = "pasted_text"
    authority_role: AuthorityRole = "authoritative"


@dataclass(frozen=True, slots=True)
class SourceVersionWrite:
    source: Source
    source_pack: SourcePack
    source_version: SourceVersion
    source_pack_version: SourcePackVersion
    asset: SourceAsset
    storage_key: str | None


def normalize_source_text(source_text: str) -> str:
    normalized = source_text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError("Source text must contain non-whitespace characters")
    if len(normalized) > SOURCE_TEXT_MAX_LENGTH:
        raise ValueError(f"Source text must be {SOURCE_TEXT_MAX_LENGTH:,} characters or fewer")
    return normalized


def segment_source_text(source_text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    paragraph_lines: list[str] = []
    heading_number = 0
    paragraph_number = 0
    page_number: int | None = None
    page_paragraph_number = 0

    def flush_paragraph() -> None:
        nonlocal paragraph_number, page_paragraph_number
        if paragraph_lines:
            if page_number is None:
                paragraph_number += 1
                locator = f"paragraph:{paragraph_number}"
            else:
                page_paragraph_number += 1
                locator = f"page:{page_number}:paragraph:{page_paragraph_number}"
            segments.append((locator, "\n".join(paragraph_lines)))
            paragraph_lines.clear()

    for line in source_text.split("\n"):
        page_heading = re.fullmatch(r"#{1,6} Page (\d+)", line, re.IGNORECASE)
        if not line.strip():
            flush_paragraph()
        elif page_heading:
            flush_paragraph()
            page_number = int(page_heading.group(1))
            page_paragraph_number = 0
            segments.append((f"page:{page_number}", line))
        elif re.fullmatch(r"#{1,6} .+", line):
            flush_paragraph()
            heading_number += 1
            locator = (
                f"page:{page_number}:heading:{heading_number}"
                if page_number is not None
                else f"heading:{heading_number}"
            )
            segments.append((locator, line))
        else:
            paragraph_lines.append(line)
    flush_paragraph()
    return segments


def validate_authority_role(value: str) -> AuthorityRole:
    if value not in {"authoritative", "supporting"}:
        raise ValueError("Source authority role is invalid")
    return value  # type: ignore[return-value]


def safe_original_filename(filename: str | None) -> str | None:
    if filename is None:
        return None
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe_name = "".join(
        character for character in basename if ord(character) >= 32 and ord(character) != 127
    )
    safe_name = safe_name[:255].strip()
    return safe_name or None


def _locator_details(locator: str) -> tuple[str, int | None]:
    page = re.match(r"^page:(\d+)(?::|$)", locator)
    if page is None:
        return locator.partition(":")[0][:32], None
    remainder = locator[len(page.group(0)) :]
    region_type = remainder.partition(":")[0] if remainder else "page"
    return region_type[:32], int(page.group(1))


def create_source_pack_version(
    session: Session,
    owner_id: int,
    source_text: str,
    *,
    source: Source | None = None,
    parent_source_version_id: int | None = None,
    asset_input: SourceAssetInput | None = None,
    storage: PrivateAssetStore | None = None,
) -> SourceVersionWrite:
    """Write one pack snapshot and its required legacy text projection together."""
    canonical_text = normalize_source_text(source_text)
    asset_input = asset_input or SourceAssetInput()
    role = validate_authority_role(asset_input.authority_role)
    if len(asset_input.media_type) > 127 or len(asset_input.extraction_method) > 40:
        raise ValueError("Source asset metadata exceeds its supported length")
    if asset_input.source_kind == "file" and asset_input.raw_bytes is None:
        raise ValueError("Uploaded source assets require their original bytes")
    if asset_input.source_kind != "file" and asset_input.raw_bytes is not None:
        raise ValueError("Raw bytes are only supported for uploaded source assets")
    if asset_input.source_kind == "url" and not asset_input.provenance_url:
        raise ValueError("URL source assets require validated provenance")
    if asset_input.source_kind != "url" and asset_input.provenance_url is not None:
        raise ValueError("Only URL source assets can include URL provenance")

    if source is None:
        source = Source(owner_id=owner_id)
        session.add(source)
    elif source.owner_id != owner_id:
        raise ValueError("Source must belong to the authenticated owner")
    session.flush()

    source_pack = session.scalar(select(SourcePack).where(SourcePack.source_id == source.id))
    if source_pack is None:
        source_pack = SourcePack(
            source_id=source.id,
            owner_id=owner_id,
            title=source.title,
            created_at=source.created_at,
        )
        session.add(source_pack)
        session.flush()
    elif source_pack.owner_id != owner_id:
        raise ValueError("Source pack must belong to the authenticated owner")

    parent_pack_version: SourcePackVersion | None = None
    if parent_source_version_id is not None:
        parent = session.scalar(
            select(SourceVersion).where(
                SourceVersion.id == parent_source_version_id,
                SourceVersion.source_id == source.id,
            )
        )
        if parent is None:
            raise ValueError("Parent source version must belong to the source")
        parent_pack_version = session.scalar(
            select(SourcePackVersion).where(
                SourcePackVersion.source_version_id == parent.id,
                SourcePackVersion.source_pack_id == source_pack.id,
            )
        )
        if parent_pack_version is None:
            raise ValueError("Parent source pack version is missing")

    latest_source_version = (
        session.scalar(
            select(func.max(SourceVersion.version_number)).where(
                SourceVersion.source_id == source.id
            )
        )
        or 0
    )
    latest_pack_version = (
        session.scalar(
            select(func.max(SourcePackVersion.version_number)).where(
                SourcePackVersion.source_pack_id == source_pack.id
            )
        )
        or 0
    )
    if latest_source_version != latest_pack_version:
        raise ValueError("Source pack and legacy source version history are inconsistent")

    created_at = utc_now()
    source_version = SourceVersion(
        source_id=source.id,
        parent_source_version_id=parent_source_version_id,
        version_number=latest_source_version + 1,
        source_text=canonical_text,
        content_hash=source_content_hash(canonical_text),
        created_at=created_at,
    )
    session.add(source_version)
    session.flush()
    source_pack_version = SourcePackVersion(
        source_pack_id=source_pack.id,
        source_version_id=source_version.id,
        parent_source_pack_version_id=(
            parent_pack_version.id if parent_pack_version is not None else None
        ),
        version_number=source_version.version_number,
        content_hash=source_version.content_hash,
        created_at=created_at,
    )
    session.add(source_pack_version)
    session.flush()

    store = storage or (get_private_asset_store() if asset_input.raw_bytes is not None else None)
    stored = None
    try:
        if asset_input.raw_bytes is not None:
            if store is None:
                raise ValueError("Private storage is required for uploaded source assets")
            stored = store.store(asset_input.raw_bytes)
            content_hash = stored.content_hash
            byte_size = stored.byte_size
            storage_key = stored.storage_key
        else:
            text_bytes = canonical_text.encode("utf-8")
            content_hash = sha256(text_bytes).hexdigest()
            byte_size = len(text_bytes)
            storage_key = None

        asset = SourceAsset(
            source_pack_version_id=source_pack_version.id,
            authority_role=role,
            source_kind=asset_input.source_kind,
            media_type=asset_input.media_type,
            original_filename=safe_original_filename(asset_input.original_filename),
            byte_size=byte_size,
            content_hash=content_hash,
            storage_key=storage_key,
            provenance_url=asset_input.provenance_url,
            extraction_method=asset_input.extraction_method,
            created_at=created_at,
        )
        session.add(asset)
        session.flush()

        segments = [
            SourceSegment(
                source_version_id=source_version.id,
                ordinal=ordinal,
                locator=locator,
                segment_text=segment_text,
            )
            for ordinal, (locator, segment_text) in enumerate(
                segment_source_text(canonical_text), 1
            )
        ]
        session.add_all(segments)
        session.flush()
        session.add_all(
            SourceRegion(
                source_asset_id=asset.id,
                source_segment_id=segment.id,
                ordinal=segment.ordinal,
                locator=segment.locator,
                region_type=_locator_details(segment.locator)[0],
                page_number=_locator_details(segment.locator)[1],
                text=segment.segment_text,
            )
            for segment in segments
        )
        session.flush()
    except Exception:
        if stored is not None and store is not None:
            try:
                store.delete(stored.storage_key)
            except OSError:
                pass
        raise

    return SourceVersionWrite(
        source=source,
        source_pack=source_pack,
        source_version=source_version,
        source_pack_version=source_pack_version,
        asset=asset,
        storage_key=storage_key,
    )


def create_source_version(
    session: Session,
    source: Source,
    source_text: str,
    parent_source_version_id: int | None = None,
) -> SourceVersion:
    asset_input = SourceAssetInput(
        extraction_method="manual_revision"
        if parent_source_version_id is not None
        else "pasted_text"
    )
    return create_source_pack_version(
        session,
        source.owner_id,
        source_text,
        source=source,
        parent_source_version_id=parent_source_version_id,
        asset_input=asset_input,
    ).source_version
