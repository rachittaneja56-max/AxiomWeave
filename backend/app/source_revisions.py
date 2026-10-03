from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ArtifactBlock,
    ArtifactBlockDependency,
    ArtifactRun,
    ArtifactVersion,
    ClaimEvidenceAssessment,
    ClaimScan,
    EvidenceLink,
    MaterialClaim,
    MaterialClaimBlock,
    SourcePackVersion,
    SourceRegionAlignment,
    SourceSegment,
    SourceVersion,
)
from app.source_alignment import align_source_versions


@dataclass(frozen=True, slots=True)
class SourceSegmentChange:
    change_type: Literal["added", "removed", "changed"]
    locator: str
    old_text: str | None
    new_text: str | None


@dataclass(frozen=True, slots=True)
class AffectedArtifactEvidence:
    artifact_run: ArtifactRun
    artifact_version: ArtifactVersion
    evidence_links: tuple[EvidenceLink, ...]
    impact_state: Literal["unaffected", "affected", "needs_review", "unknown"] = "unknown"
    affected_block_keys: tuple[str, ...] = ()
    review_block_keys: tuple[str, ...] = ()
    unknown_block_keys: tuple[str, ...] = ()
    targeted_update_available: bool = False


def diff_source_versions(
    session: Session, old_version: SourceVersion, new_version: SourceVersion
) -> list[SourceSegmentChange]:
    old_segments = list(
        session.scalars(
            select(SourceSegment)
            .where(SourceSegment.source_version_id == old_version.id)
            .order_by(SourceSegment.ordinal)
        ).all()
    )
    new_segments = list(
        session.scalars(
            select(SourceSegment)
            .where(SourceSegment.source_version_id == new_version.id)
            .order_by(SourceSegment.ordinal)
        ).all()
    )
    old_by_locator = {segment.locator: segment for segment in old_segments}
    new_by_locator = {segment.locator: segment for segment in new_segments}
    locators = list(
        dict.fromkeys(
            [*(item.locator for item in old_segments), *(item.locator for item in new_segments)]
        )
    )
    changes: list[SourceSegmentChange] = []
    for locator in locators:
        old_segment = old_by_locator.get(locator)
        new_segment = new_by_locator.get(locator)
        if old_segment is None and new_segment is not None:
            changes.append(SourceSegmentChange("added", locator, None, new_segment.segment_text))
        elif new_segment is None and old_segment is not None:
            changes.append(SourceSegmentChange("removed", locator, old_segment.segment_text, None))
        elif (
            old_segment is not None
            and new_segment is not None
            and old_segment.segment_text != new_segment.segment_text
        ):
            changes.append(
                SourceSegmentChange(
                    "changed", locator, old_segment.segment_text, new_segment.segment_text
                )
            )
    return changes


def find_potentially_affected_artifacts(
    session: Session,
    old_version: SourceVersion,
    new_version: SourceVersion,
    changes: list[SourceSegmentChange],
) -> list[AffectedArtifactEvidence]:
    del changes  # The legacy locator diff is display-only; it is not impact authority.
    old_pack = session.scalar(
        select(SourcePackVersion).where(SourcePackVersion.source_version_id == old_version.id)
    )
    new_pack = session.scalar(
        select(SourcePackVersion).where(SourcePackVersion.source_version_id == new_version.id)
    )
    if (
        old_pack is None
        or new_pack is None
        or new_version.parent_source_version_id != old_version.id
    ):
        return []
    alignments = list(
        session.scalars(
            select(SourceRegionAlignment).where(
                SourceRegionAlignment.parent_pack_version_id == old_pack.id,
                SourceRegionAlignment.child_pack_version_id == new_pack.id,
            )
        )
    )
    if not alignments:
        alignments = align_source_versions(session, old_version, new_version)
    by_old_region: dict[int, list[SourceRegionAlignment]] = {}
    has_added_material = False
    for alignment in alignments:
        if alignment.old_region_id is not None:
            by_old_region.setdefault(alignment.old_region_id, []).append(alignment)
        if alignment.alignment_state == "added":
            has_added_material = True

    versions = session.execute(
        select(ArtifactVersion, ArtifactRun)
        .join(ArtifactRun, ArtifactRun.id == ArtifactVersion.artifact_run_id)
        .where(ArtifactVersion.source_version_id == old_version.id)
        .order_by(ArtifactRun.id, ArtifactVersion.version_number.desc())
    ).all()
    impacts: list[AffectedArtifactEvidence] = []
    for version, run in versions:
        blocks = list(
            session.scalars(
                select(ArtifactBlock)
                .where(ArtifactBlock.artifact_version_id == version.id)
                .order_by(ArtifactBlock.ordinal)
            )
        )
        if not blocks:
            links = tuple(
                session.scalars(
                    select(EvidenceLink).where(EvidenceLink.artifact_version_id == version.id)
                )
            )
            impacts.append(AffectedArtifactEvidence(run, version, links, "unknown"))
            continue

        affected_keys: list[str] = []
        review_keys: list[str] = []
        unknown_keys: list[str] = []
        block_states: dict[int, str] = {}
        claim_scan = session.scalar(
            select(ClaimScan).where(ClaimScan.artifact_version_id == version.id)
        )
        claim_coverage_is_complete = False
        if claim_scan is not None and claim_scan.status == "complete":
            claim_coverage_is_complete = (
                session.scalar(
                    select(MaterialClaim.id)
                    .where(
                        MaterialClaim.claim_scan_id == claim_scan.id,
                        MaterialClaim.block_mapping_state != "validated",
                    )
                    .limit(1)
                )
                is None
            )
        for block in blocks:
            claim_ids = list(
                session.scalars(
                    select(MaterialClaimBlock.material_claim_id).where(
                        MaterialClaimBlock.artifact_block_id == block.id
                    )
                )
            )
            dependencies = list(
                session.scalars(
                    select(ArtifactBlockDependency).where(
                        ArtifactBlockDependency.artifact_block_id == block.id
                    )
                )
            )
            dependency_states: list[str] = []
            if not dependencies:
                dependency_states.append(
                    "unaffected" if claim_coverage_is_complete and not claim_ids else "unknown"
                )
            for dependency in dependencies:
                candidates = by_old_region.get(dependency.source_region_id, [])
                if len(candidates) != 1:
                    dependency_states.append("unknown" if not candidates else "needs_review")
                    continue
                alignment = candidates[0]
                if alignment.alignment_state in {"ambiguous", "split", "merged"}:
                    dependency_states.append("needs_review")
                elif alignment.alignment_state in {"changed", "removed"}:
                    dependency_states.append("affected")
                elif alignment.alignment_state in {"unchanged", "moved"}:
                    if dependency.source_content_hash != _region_content_hash(
                        session, dependency.source_region_id
                    ):
                        dependency_states.append("affected")
                    else:
                        dependency_states.append("unaffected")
                else:
                    dependency_states.append("unknown")
            state = max(
                dependency_states or ["unknown"],
                key={"unaffected": 0, "affected": 1, "unknown": 2, "needs_review": 3}.__getitem__,
            )

            if claim_ids:
                assessments = list(
                    session.scalars(
                        select(ClaimEvidenceAssessment).where(
                            ClaimEvidenceAssessment.material_claim_id.in_(claim_ids),
                            ClaimEvidenceAssessment.artifact_version_id == version.id,
                        )
                    )
                )
                if any(
                    assessment.evidence_state
                    in {"partial", "contradicted", "missing", "ambiguous", "conflict"}
                    for assessment in assessments
                ):
                    state = "needs_review"
            block_states[block.id] = state
            if state == "affected":
                affected_keys.append(block.block_key)
            elif state == "needs_review":
                review_keys.append(block.block_key)
            elif state == "unknown":
                unknown_keys.append(block.block_key)

        if has_added_material:
            unknown_keys.extend(
                block.block_key for block in blocks if block.block_key not in unknown_keys
            )
        if review_keys:
            status: Literal["unaffected", "affected", "needs_review", "unknown"] = "needs_review"
        elif has_added_material:
            status = "unknown"
        elif unknown_keys:
            status = "unknown"
        elif affected_keys:
            status = "affected"
        else:
            status = "unaffected"
        if status == "unaffected":
            continue

        relevant_claim_ids = [
            claim_id
            for block in blocks
            if block_states.get(block.id) in {"affected", "needs_review"}
            for claim_id in session.scalars(
                select(MaterialClaimBlock.material_claim_id).where(
                    MaterialClaimBlock.artifact_block_id == block.id
                )
            )
        ]
        links = tuple(
            session.scalars(
                select(EvidenceLink).where(
                    EvidenceLink.artifact_version_id == version.id,
                    EvidenceLink.material_claim_id.in_(relevant_claim_ids)
                    if relevant_claim_ids
                    else EvidenceLink.id < 0,
                )
            )
        )
        safe = status == "affected" and not review_keys and not unknown_keys and bool(affected_keys)
        impacts.append(
            AffectedArtifactEvidence(
                run,
                version,
                links,
                status,
                tuple(affected_keys),
                tuple(review_keys),
                tuple(unknown_keys),
                safe,
            )
        )
    return impacts


def _region_content_hash(session: Session, source_region_id: int) -> str | None:
    from hashlib import sha256

    from app.models import SourceRegion

    region = session.get(SourceRegion, source_region_id)
    if region is None or region.text is None:
        return None
    return sha256(region.text.encode("utf-8")).hexdigest()
