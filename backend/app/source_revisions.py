from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ArtifactRun,
    ArtifactVersion,
    EvidenceLink,
    SourceSegment,
    SourceVersion,
)


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
    changed_locators = {
        change.locator for change in changes if change.change_type in {"changed", "removed"}
    }
    evidence_links = list(
        session.scalars(
            select(EvidenceLink)
            .where(
                EvidenceLink.source_version_id == old_version.id,
                EvidenceLink.status == "linked",
            )
            .order_by(EvidenceLink.id)
        ).all()
    )
    affected_by_version: dict[int, tuple[ArtifactRun, ArtifactVersion, list[EvidenceLink]]] = {}
    for link in evidence_links:
        affected = False
        if link.source_segment_id is not None:
            segment = session.get(SourceSegment, link.source_segment_id)
            affected = segment is not None and segment.locator in changed_locators
        elif link.source_quote is not None:
            affected = link.source_quote not in new_version.source_text
        if not affected:
            continue
        row = session.execute(
            select(ArtifactVersion, ArtifactRun)
            .join(ArtifactRun, ArtifactRun.id == ArtifactVersion.artifact_run_id)
            .where(ArtifactVersion.id == link.artifact_version_id)
        ).first()
        if row is None:
            continue
        version, run = row
        if version.id not in affected_by_version:
            affected_by_version[version.id] = (run, version, [])
        affected_by_version[version.id][2].append(link)
    return [
        AffectedArtifactEvidence(run, version, tuple(links))
        for run, version, links in affected_by_version.values()
    ]
