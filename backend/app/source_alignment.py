"""Deterministic SourceRegion alignment for exact parent/child source-pack snapshots."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceRegionAlignment,
    SourceVersion,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class RegionAlignmentDraft:
    old_region: SourceRegion | None
    new_region: SourceRegion | None
    state: str


@dataclass(frozen=True, slots=True)
class RegionRef:
    region: SourceRegion
    role: str
    membership_ordinal: int

    @property
    def content_hash(self) -> str:
        return sha256((self.region.text or "").encode("utf-8")).hexdigest()

    @property
    def anchor(self) -> tuple[str, str, int | None, str]:
        return (
            self.role,
            self.region.region_type,
            self.region.page_number,
            self.region.locator,
        )


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def align_regions(
    old_regions: list[RegionRef], new_regions: list[RegionRef]
) -> list[RegionAlignmentDraft]:
    """Align exact content first, then structural anchors; unresolved moves stay ambiguous."""
    rows: list[RegionAlignmentDraft] = []
    old_remaining = {item.region.id: item for item in old_regions}
    new_remaining = {item.region.id: item for item in new_regions}

    old_by_hash: dict[str, list[RegionRef]] = defaultdict(list)
    new_by_hash: dict[str, list[RegionRef]] = defaultdict(list)
    for item in old_regions:
        old_by_hash[item.content_hash].append(item)
    for item in new_regions:
        new_by_hash[item.content_hash].append(item)

    for content_hash, old_items in old_by_hash.items():
        new_items = new_by_hash.get(content_hash, [])
        if len(old_items) == 1 and len(new_items) == 1:
            old_item, new_item = old_items[0], new_items[0]
            if old_item.region.text == new_item.region.text:
                state = "unchanged" if old_item.anchor == new_item.anchor else "moved"
                rows.append(RegionAlignmentDraft(old_item.region, new_item.region, state))
                old_remaining.pop(old_item.region.id, None)
                new_remaining.pop(new_item.region.id, None)
            continue
        if not old_items or not new_items:
            continue
        anchors_old: dict[tuple[str, str, int | None, str], list[RegionRef]] = defaultdict(list)
        anchors_new: dict[tuple[str, str, int | None, str], list[RegionRef]] = defaultdict(list)
        for item in old_items:
            anchors_old[item.anchor].append(item)
        for item in new_items:
            anchors_new[item.anchor].append(item)
        for anchor, old_matches in anchors_old.items():
            new_matches = anchors_new.get(anchor, [])
            if len(old_matches) == len(new_matches) == 1:
                old_item, new_item = old_matches[0], new_matches[0]
                rows.append(RegionAlignmentDraft(old_item.region, new_item.region, "unchanged"))
                old_remaining.pop(old_item.region.id, None)
                new_remaining.pop(new_item.region.id, None)
        old_unmatched = [item for item in old_items if item.region.id in old_remaining]
        new_unmatched = [item for item in new_items if item.region.id in new_remaining]
        if old_unmatched and new_unmatched:
            for old_item in old_unmatched:
                for new_item in new_unmatched:
                    rows.append(RegionAlignmentDraft(old_item.region, new_item.region, "ambiguous"))
                old_remaining.pop(old_item.region.id, None)
            for new_item in new_unmatched:
                new_remaining.pop(new_item.region.id, None)

    # Detect exact normalized splits and merges over bounded adjacent region groups.
    def adjacent_groups(items: list[RegionRef]) -> list[list[RegionRef]]:
        groups: list[list[RegionRef]] = []
        for item in items:
            if (
                not groups
                or groups[-1][-1].role != item.role
                or groups[-1][-1].region.source_asset_id != item.region.source_asset_id
                or item.region.ordinal != groups[-1][-1].region.ordinal + 1
            ):
                groups.append([item])
            else:
                groups[-1].append(item)
        return groups

    old_unmatched_items = [item for item in old_regions if item.region.id in old_remaining]
    new_unmatched_items = [item for item in new_regions if item.region.id in new_remaining]
    for old_item in old_unmatched_items:
        for group in adjacent_groups(new_unmatched_items):
            if not 2 <= len(group) <= 4 or group[0].role != old_item.role:
                continue
            combined = " ".join(item.region.text or "" for item in group)
            if _normalize(old_item.region.text) == _normalize(combined):
                rows.extend(
                    RegionAlignmentDraft(old_item.region, item.region, "split") for item in group
                )
                old_remaining.pop(old_item.region.id, None)
                for item in group:
                    new_remaining.pop(item.region.id, None)
                break

    old_unmatched_items = [item for item in old_regions if item.region.id in old_remaining]
    new_unmatched_items = [item for item in new_regions if item.region.id in new_remaining]
    for new_item in new_unmatched_items:
        for group in adjacent_groups(old_unmatched_items):
            if not 2 <= len(group) <= 4 or group[0].role != new_item.role:
                continue
            combined = " ".join(item.region.text or "" for item in group)
            if _normalize(combined) == _normalize(new_item.region.text):
                rows.extend(
                    RegionAlignmentDraft(item.region, new_item.region, "merged") for item in group
                )
                for item in group:
                    old_remaining.pop(item.region.id, None)
                new_remaining.pop(new_item.region.id, None)
                break

    # A unique structural anchor with different content is changed, not moved.
    old_anchor: dict[tuple[str, str, int | None, str], list[RegionRef]] = defaultdict(list)
    new_anchor: dict[tuple[str, str, int | None, str], list[RegionRef]] = defaultdict(list)
    for item in old_remaining.values():
        old_anchor[item.anchor].append(item)
    for item in new_remaining.values():
        new_anchor[item.anchor].append(item)
    for anchor, old_matches in old_anchor.items():
        new_matches = new_anchor.get(anchor, [])
        if len(old_matches) == len(new_matches) == 1:
            old_item, new_item = old_matches[0], new_matches[0]
            rows.append(RegionAlignmentDraft(old_item.region, new_item.region, "changed"))
            old_remaining.pop(old_item.region.id, None)
            new_remaining.pop(new_item.region.id, None)

    rows.extend(
        RegionAlignmentDraft(item.region, None, "removed") for item in old_remaining.values()
    )
    rows.extend(RegionAlignmentDraft(None, item.region, "added") for item in new_remaining.values())
    return rows


def _pack_version(session: Session, source_version: SourceVersion) -> SourcePackVersion:
    result = session.scalar(
        select(SourcePackVersion).where(SourcePackVersion.source_version_id == source_version.id)
    )
    if result is None:
        raise ValueError("Source version has no immutable source-pack snapshot")
    source = session.get(Source, source_version.source_id)
    if source is None:
        raise ValueError("Source owner is unavailable")
    pack = session.scalar(select(SourcePack).where(SourcePack.source_id == source.id))
    if pack is None or pack.owner_id != source.owner_id or result.source_pack_id != pack.id:
        raise ValueError("Source pack does not match the source owner")
    return result


def _region_refs(session: Session, pack_version: SourcePackVersion) -> list[RegionRef]:
    records = session.execute(
        select(SourceRegion, SourcePackMembership.role, SourcePackMembership.ordinal)
        .join(SourceAsset, SourceAsset.id == SourceRegion.source_asset_id)
        .join(SourcePackMembership, SourcePackMembership.source_asset_id == SourceAsset.id)
        .where(SourcePackMembership.source_pack_version_id == pack_version.id)
        .order_by(SourcePackMembership.ordinal, SourceRegion.ordinal, SourceRegion.id)
    ).all()
    return [RegionRef(region, role, ordinal) for region, role, ordinal in records]


def align_source_versions(
    session: Session, old_version: SourceVersion, new_version: SourceVersion
) -> list[SourceRegionAlignment]:
    """Persist deterministic alignment for a direct parent/child source-version pair."""
    if new_version.parent_source_version_id != old_version.id:
        raise ValueError("Source regions can only be aligned across an exact parent/child pair")
    old_pack = _pack_version(session, old_version)
    new_pack = _pack_version(session, new_version)
    if old_pack.source_pack_id != new_pack.source_pack_id:
        raise ValueError("Source versions belong to different source packs")
    existing = list(
        session.scalars(
            select(SourceRegionAlignment).where(
                SourceRegionAlignment.parent_pack_version_id == old_pack.id,
                SourceRegionAlignment.child_pack_version_id == new_pack.id,
            )
        )
    )
    if existing:
        return existing
    drafts = align_regions(_region_refs(session, old_pack), _region_refs(session, new_pack))
    rows = [
        SourceRegionAlignment(
            parent_pack_version_id=old_pack.id,
            child_pack_version_id=new_pack.id,
            old_region_id=draft.old_region.id if draft.old_region is not None else None,
            new_region_id=draft.new_region.id if draft.new_region is not None else None,
            alignment_state=draft.state,
            created_at=utc_now(),
        )
        for draft in drafts
    ]
    session.add_all(rows)
    session.flush()
    return rows
