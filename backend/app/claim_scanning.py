"""Deterministic bounded work units and coverage semantics for material-claim analysis."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifact_contracts import artifact_text_projection
from app.domain.transformation import OutputType
from app.models import ArtifactRun, ArtifactVersion, ClaimBatch, ClaimScan, MaterialClaim, utc_now

CLAIM_EXTRACTION_PROFILE = "material-claim-scan"
CLAIM_EXTRACTION_PROFILE_VERSION = 1
CLAIM_BATCH_MAX_CHARS = 2_000


def deterministic_text_ranges(
    text: str, max_chars: int = CLAIM_BATCH_MAX_CHARS
) -> list[tuple[int, int]]:
    """Split on paragraph/whitespace boundaries where possible, preserving every code point."""
    if max_chars < 1:
        raise ValueError("Batch size must be positive")
    if not text:
        return [(0, 0)]
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        if hard_end == len(text):
            end = hard_end
        else:
            floor = start + max(1, max_chars // 2)
            paragraph_end = text.rfind("\n\n", floor, hard_end)
            newline_end = text.rfind("\n", floor, hard_end)
            whitespace_end = max(
                text.rfind(" ", floor, hard_end),
                text.rfind("\t", floor, hard_end),
            )
            if paragraph_end >= floor:
                end = paragraph_end + 2
            elif newline_end >= floor:
                end = newline_end + 1
            elif whitespace_end >= floor:
                end = whitespace_end + 1
            else:
                end = hard_end
        if end <= start:
            end = hard_end
        ranges.append((start, end))
        start = end
    return ranges


def create_or_get_claim_scan(
    session: Session, owner_id: int, artifact_version: ArtifactVersion
) -> ClaimScan:
    scan = session.scalar(
        select(ClaimScan).where(ClaimScan.artifact_version_id == artifact_version.id)
    )
    if scan is not None:
        if scan.owner_id != owner_id:
            raise ValueError("Claim scan owner does not match artifact owner")
        return scan
    artifact_run = session.get(ArtifactRun, artifact_version.artifact_run_id)
    if artifact_run is None:
        raise ValueError("Artifact run is unavailable")
    projection = artifact_text_projection(
        OutputType(artifact_run.output_type), artifact_version.content
    )
    scan = ClaimScan(
        owner_id=owner_id,
        artifact_version_id=artifact_version.id,
        source_version_id=artifact_version.source_version_id,
        status="pending",
        text_projection=projection,
        extraction_profile=CLAIM_EXTRACTION_PROFILE,
        extraction_profile_version=CLAIM_EXTRACTION_PROFILE_VERSION,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(scan)
    session.flush()
    session.add_all(
        ClaimBatch(
            claim_scan_id=scan.id,
            ordinal=ordinal,
            text_start=start,
            text_end=end,
            input_hash=sha256(projection[start:end].encode("utf-8")).hexdigest(),
            extraction_profile=CLAIM_EXTRACTION_PROFILE,
            extraction_profile_version=CLAIM_EXTRACTION_PROFILE_VERSION,
            status="pending",
            attempt_count=0,
        )
        for ordinal, (start, end) in enumerate(deterministic_text_ranges(projection), 1)
    )
    session.flush()
    refresh_scan_status(session, scan)
    return scan


def refresh_scan_status(session: Session, scan: ClaimScan) -> ClaimScan:
    batches = list(session.scalars(select(ClaimBatch).where(ClaimBatch.claim_scan_id == scan.id)))
    if batches and all(batch.status == "complete" for batch in batches):
        scan.status = "complete"
    elif any(batch.status == "needs_review" for batch in batches):
        scan.status = "needs_review"
    elif any(batch.status == "failed" for batch in batches):
        scan.status = "failed"
    elif any(batch.status == "running" for batch in batches):
        scan.status = "running"
    else:
        scan.status = "pending"
    scan.updated_at = utc_now()
    return scan


def claim_scan_coverage(session: Session, scan: ClaimScan) -> dict[str, int | str]:
    batches = list(session.scalars(select(ClaimBatch).where(ClaimBatch.claim_scan_id == scan.id)))
    claims_found = (
        session.scalar(
            select(func.count(MaterialClaim.id)).where(MaterialClaim.claim_scan_id == scan.id)
        )
        or 0
    )
    return {
        "total_batches": len(batches),
        "completed_batches": sum(batch.status == "complete" for batch in batches),
        "failed_batches": sum(batch.status == "failed" for batch in batches),
        "needs_review_batches": sum(batch.status == "needs_review" for batch in batches),
        "claims_found": claims_found,
        "status": scan.status,
    }


def batch_input_text(
    artifact_version: ArtifactVersion, batch: ClaimBatch, text_projection: str | None = None
) -> str:
    source_text = text_projection if text_projection is not None else artifact_version.content
    value = source_text[batch.text_start : batch.text_end]
    if sha256(value.encode("utf-8")).hexdigest() != batch.input_hash:
        raise ValueError("Artifact claim batch no longer matches its exact text snapshot")
    return value
