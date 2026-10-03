"""Deterministic, R0-first source context planning and manifest assembly."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models import (
    ArtifactRun,
    ContextManifest,
    ContextManifestEntry,
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceVersion,
    TransformationRun,
    utc_now,
)
from app.source_roles import source_role_policy

CONTEXT_BUDGET_POLICY_VERSION = "context-chars-v1"
CONTEXT_ESTIMATION_METHOD = "unicode-codepoint-count-v1"
CONTEXT_BUDGET_UNITS = 20_000
RESERVED_OUTPUT_SCHEMA_EVIDENCE_MARGIN = 5_000
AVAILABLE_INPUT_BUDGET = CONTEXT_BUDGET_UNITS + RESERVED_OUTPUT_SCHEMA_EVIDENCE_MARGIN
R0_PROFILE = "r0_full_context"
R0_PROFILE_VERSION = 1


class ContextPlanNeedsReview(ValueError):
    pass


def plan_context_manifest(
    session: Session,
    transformation: TransformationRun,
    artifact_run: ArtifactRun,
    source_version: SourceVersion,
    *,
    task_class: str = "artifact_generation",
) -> ContextManifest:
    """Persist the exact factual regions and budget decision for one queued job."""
    row = session.execute(
        select(SourcePack, SourcePackVersion)
        .join(SourcePackVersion, SourcePackVersion.source_pack_id == SourcePack.id)
        .where(
            SourcePack.owner_id == transformation.owner_id,
            SourcePackVersion.source_version_id == source_version.id,
        )
    ).one_or_none()
    if row is None:
        raise ValueError("A context manifest requires an owned immutable source-pack version")
    source_pack, pack_version = row

    asset_pack_version = aliased(SourcePackVersion)
    membership_rows = session.execute(
        select(SourcePackMembership, SourceAsset, SourceVersion, Source)
        .join(SourceAsset, SourceAsset.id == SourcePackMembership.source_asset_id)
        .join(asset_pack_version, asset_pack_version.id == SourceAsset.source_pack_version_id)
        .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(
            SourcePackMembership.source_pack_version_id == pack_version.id,
            asset_pack_version.source_version_id == SourcePackMembership.source_version_id,
            Source.owner_id == transformation.owner_id,
        )
        .order_by(SourcePackMembership.ordinal, SourceAsset.id)
    ).all()
    if not membership_rows:
        raise ValueError("The source-pack snapshot has no validated memberships")

    warnings: list[str] = []
    coverage_states: list[str] = []
    selected: list[
        tuple[SourcePackMembership, SourceAsset, SourceRegion, SourceVersion, Source]
    ] = []
    for membership, asset, member_source, source in membership_rows:
        if not source_role_policy(membership.role).may_ground_facts:
            continue
        coverage_states.append(asset.extraction_coverage)
        if asset.extraction_coverage == "partial":
            warnings.append(f"partial_extraction:asset:{asset.id}")
        elif asset.extraction_coverage == "unavailable":
            warnings.append(f"extraction_unavailable:asset:{asset.id}")
        regions = list(
            session.scalars(
                select(SourceRegion)
                .where(SourceRegion.source_asset_id == asset.id)
                .order_by(SourceRegion.ordinal, SourceRegion.id)
            ).all()
        )
        for region in regions:
            if region.text is None:
                warnings.append(f"non_text_region_omitted:region:{region.id}")
                continue
            selected.append((membership, asset, region, member_source, source))
    if not selected:
        warnings.append("no_text_regions_available")

    primary_regions = [row for row in selected if row[0].role == "PRIMARY"]
    if not primary_regions:
        warnings.append("primary_text_unavailable")
    context_text = _render_r0_context(source_version, selected)
    estimated_units = len(context_text) + len(transformation.supporting_context)
    has_primary_text = bool(primary_regions)
    state = (
        "ready" if estimated_units <= CONTEXT_BUDGET_UNITS and has_primary_text else "needs_review"
    )
    if estimated_units > CONTEXT_BUDGET_UNITS:
        warnings.append("context_over_budget_no_admitted_r1_profile")

    coverage = "partial" if "partial" in coverage_states or warnings else "complete"
    manifest = ContextManifest(
        owner_id=transformation.owner_id,
        source_pack_id=source_pack.id,
        source_pack_version_id=pack_version.id,
        source_version_id=source_version.id,
        task_class=task_class,
        artifact_family=artifact_run.output_type,
        route="R0_FULL_CONTEXT",
        context_profile=R0_PROFILE,
        context_profile_version=R0_PROFILE_VERSION,
        query_construction_version=1,
        budget_policy_version=CONTEXT_BUDGET_POLICY_VERSION,
        estimation_method=CONTEXT_ESTIMATION_METHOD,
        context_budget_units=CONTEXT_BUDGET_UNITS,
        available_input_budget=AVAILABLE_INPUT_BUDGET,
        estimated_context_units=estimated_units,
        reserved_margin=RESERVED_OUTPUT_SCHEMA_EVIDENCE_MARGIN,
        extraction_coverage=coverage,
        state=state,
        warnings=sorted(set(warnings)),
        created_at=utc_now(),
    )
    session.add(manifest)
    session.flush()
    entries: list[ContextManifestEntry] = []
    for membership, asset, region, _member_source, _source in selected:
        if region.text is None:
            raise ValueError("A selected context region must contain text")
        entries.append(
            ContextManifestEntry(
                context_manifest_id=manifest.id,
                source_region_id=region.id,
                source_asset_id=asset.id,
                membership_id=membership.id,
                role=membership.role,
                selected=True,
                locator=region.locator,
                content_hash=sha256(region.text.encode("utf-8")).hexdigest(),
                estimated_context_units=len(region.text),
                reason="r0_all_eligible_factual_regions",
                profile_metadata={"profile": R0_PROFILE, "version": R0_PROFILE_VERSION},
            )
        )
    session.add_all(entries)
    session.flush()
    return manifest


def _render_r0_context(
    primary_source: SourceVersion,
    selected: list[tuple[SourcePackMembership, SourceAsset, SourceRegion, SourceVersion, Source]],
) -> str:
    """Keep the legacy primary source byte-for-byte; append factual supporting material."""
    supporting_rows = [row for row in selected if row[0].role == "SUPPORTING"]
    if not supporting_rows:
        return primary_source.source_text

    parts = [primary_source.source_text]
    for _membership, asset, region, member_source, source in supporting_rows:
        if region.text is None:
            raise ValueError("A selected context region must contain text")
        label = source.title or asset.original_filename or f"source {source.id}"
        parts.append(
            f"[SUPPORTING source: {label}; version {member_source.version_number}; "
            f"locator: {region.locator}]\n{region.text}"
        )
    return "\n\n".join(part for part in parts if part)


def context_text_from_manifest(session: Session, manifest: ContextManifest) -> str:
    """Render the frozen selection without rerunning retrieval or consulting newer versions."""
    entries = list(
        session.execute(
            select(
                ContextManifestEntry,
                SourceRegion,
                SourceAsset,
                SourcePackMembership,
                SourceVersion,
                Source,
            )
            .join(SourceRegion, SourceRegion.id == ContextManifestEntry.source_region_id)
            .join(SourceAsset, SourceAsset.id == ContextManifestEntry.source_asset_id)
            .join(
                SourcePackMembership, SourcePackMembership.id == ContextManifestEntry.membership_id
            )
            .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                ContextManifestEntry.context_manifest_id == manifest.id,
                ContextManifestEntry.selected.is_(True),
            )
            .order_by(SourcePackMembership.ordinal, SourceRegion.ordinal, SourceRegion.id)
        ).all()
    )
    if manifest.state != "ready":
        raise ContextPlanNeedsReview("The context manifest requires review before generation")
    if not entries:
        raise ValueError("The context manifest contains no selected text regions")
    if any(not manifest_entry_is_valid(session, manifest, row[0]) for row in entries):
        raise ValueError("The context manifest contains an invalid or unauthorized region")
    if manifest.route == "R0_FULL_CONTEXT":
        primary_source = session.get(SourceVersion, manifest.source_version_id)
        if primary_source is None:
            raise ValueError("The context manifest source snapshot is unavailable")
        primary_members = [
            membership
            for _entry, _region, _asset, membership, _member_source, _source in entries
            if membership.role == "PRIMARY"
        ]
        if any(member.source_version_id == primary_source.id for member in primary_members):
            parts = [primary_source.source_text]
            for _entry, region, asset, membership, member_source, source in entries:
                if membership.role == "SUPPORTING":
                    if region.text is None:
                        raise ValueError("A selected context region must contain text")
                    label = source.title or asset.original_filename or f"source {source.id}"
                    parts.append(
                        f"[SUPPORTING source: {label}; version {member_source.version_number}; "
                        f"locator: {region.locator}]\n{region.text}"
                    )
            return "\n\n".join(parts)

    parts: list[str] = []
    current_member: int | None = None
    current_role: str | None = None
    current_regions: list[tuple[str, str]] = []
    current_name: str | None = None
    current_version: int | None = None

    def flush() -> None:
        if not current_regions:
            return
        for locator, text_value in current_regions:
            parts.append(
                f"[{current_role} source: {current_name or current_member}; "
                f"version {current_version}; locator: {locator}]\n{text_value}"
            )

    for _entry, region, asset, membership, member_source, source in entries:
        if region.text is None:
            continue
        if membership.id != current_member:
            flush()
            current_member = membership.id
            current_role = membership.role
            current_name = source.title or asset.original_filename or f"source {source.id}"
            current_version = member_source.version_number
            current_regions = []
        current_regions.append((region.locator, region.text))
    flush()
    if not parts:
        raise ValueError("The context manifest selected no renderable text")
    return "\n\n".join(parts)


def manifest_entry_is_valid(
    session: Session, manifest: ContextManifest, entry: ContextManifestEntry
) -> bool:
    """Recheck exact owner, pack-version, role, asset, and region membership before use."""
    asset_pack_version = aliased(SourcePackVersion)
    region = session.scalar(
        select(SourceRegion)
        .join(SourceAsset, SourceAsset.id == SourceRegion.source_asset_id)
        .join(SourcePackMembership, SourcePackMembership.source_asset_id == SourceAsset.id)
        .join(
            SourcePackVersion, SourcePackVersion.id == SourcePackMembership.source_pack_version_id
        )
        .join(asset_pack_version, asset_pack_version.id == SourceAsset.source_pack_version_id)
        .join(SourcePack, SourcePack.id == SourcePackVersion.source_pack_id)
        .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(
            SourceRegion.id == entry.source_region_id,
            SourceAsset.id == entry.source_asset_id,
            SourcePackMembership.id == entry.membership_id,
            SourcePackMembership.source_pack_version_id == manifest.source_pack_version_id,
            asset_pack_version.source_version_id == SourcePackMembership.source_version_id,
            SourcePackVersion.id == manifest.source_pack_version_id,
            SourcePack.id == manifest.source_pack_id,
            SourcePack.owner_id == manifest.owner_id,
            Source.owner_id == manifest.owner_id,
            SourcePackMembership.role == entry.role,
            SourcePackMembership.role.in_(("PRIMARY", "SUPPORTING")),
        )
    )
    return (
        region is not None
        and region.text is not None
        and sha256(region.text.encode("utf-8")).hexdigest() == entry.content_hash
    )
