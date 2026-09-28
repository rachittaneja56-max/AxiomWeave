import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.transformation import SOURCE_TEXT_MAX_LENGTH
from app.models import Source, SourceSegment, SourceVersion, source_content_hash


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

    def flush_paragraph() -> None:
        nonlocal paragraph_number
        if paragraph_lines:
            paragraph_number += 1
            segments.append((f"paragraph:{paragraph_number}", "\n".join(paragraph_lines)))
            paragraph_lines.clear()

    for line in source_text.split("\n"):
        if not line.strip():
            flush_paragraph()
        elif re.fullmatch(r"#{1,6} .+", line):
            flush_paragraph()
            heading_number += 1
            segments.append((f"heading:{heading_number}", line))
        else:
            paragraph_lines.append(line)
    flush_paragraph()
    return segments


def create_source_version(session: Session, source: Source, source_text: str) -> SourceVersion:
    canonical_text = normalize_source_text(source_text)
    latest_version = session.scalar(
        select(func.max(SourceVersion.version_number)).where(SourceVersion.source_id == source.id)
    )
    version = SourceVersion(
        source_id=source.id,
        version_number=(latest_version or 0) + 1,
        source_text=canonical_text,
        content_hash=source_content_hash(canonical_text),
    )
    session.add(version)
    session.flush()
    session.add_all(
        SourceSegment(
            source_version_id=version.id,
            ordinal=ordinal,
            locator=locator,
            segment_text=segment_text,
        )
        for ordinal, (locator, segment_text) in enumerate(
            segment_source_text(canonical_text), start=1
        )
    )
    return version
