"""Deterministic artifact block extraction and mechanically validated provenance edges."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifact_contracts import (
    InfographicCalloutBlock,
    InfographicSectionBlock,
    InfographicSpec,
    VideoPackageSpec,
    artifact_text_projection,
    validate_artifact_content,
)
from app.domain.transformation import OutputType
from app.models import (
    ArtifactBlock,
    ArtifactBlockDependency,
    ArtifactRun,
    ArtifactVersion,
    ClaimScan,
    ContextManifest,
    ContextManifestEntry,
    KnowledgeAssertion,
    LineageProposal,
    MaterialClaim,
    MaterialClaimBlock,
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceRegionAlignment,
    SourceVersion,
    TransformationRun,
    User,
    utc_now,
)
from app.presentation import PresentationSpec


class LineageProposalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_key: str = Field(min_length=1, max_length=255)
    claim_text: str = Field(min_length=1, max_length=1_000)
    source_region_id: int | None = Field(default=None, gt=0, le=2**63 - 1)
    knowledge_assertion_id: int | None = Field(default=None, gt=0, le=2**63 - 1)
    source_quote: str = Field(default="", max_length=2_000)
    quote_start: int | None = Field(default=None, ge=0)
    quote_end: int | None = Field(default=None, ge=0)


class LineageProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[LineageProposalItem] = Field(max_length=256)


LINEAGE_PROPOSAL_PROFILE = "artifact-lineage-proposal"
LINEAGE_PROPOSAL_PROFILE_VERSION = 1


@dataclass(frozen=True, slots=True)
class BlockDraft:
    block_key: str
    ordinal: int
    block_type: str
    visible_text: str
    structural_metadata: dict[str, object] | None = None

    @property
    def content_hash(self) -> str:
        return sha256(self.visible_text.encode("utf-8")).hexdigest()


def _block(key: str, kind: str, value: str, **metadata: object) -> BlockDraft | None:
    if not value.strip():
        return None
    return BlockDraft(key, 0, kind, value, metadata or None)


def extract_artifact_blocks(output_type: OutputType, content: str) -> list[BlockDraft]:
    """Split validated human-visible content into stable, family-specific blocks."""
    contract_model = {
        OutputType.PRESENTATION: PresentationSpec,
        OutputType.INFOGRAPHIC: InfographicSpec,
        OutputType.VIDEO_PACKAGE: VideoPackageSpec,
    }.get(output_type)

    blocks: list[BlockDraft] = []
    if contract_model is None:
        paragraphs = [part for part in re.split(r"\n\s*\n", content.strip()) if part.strip()]
        blocks = [
            BlockDraft(f"paragraph:{index}", index, "paragraph", paragraph)
            for index, paragraph in enumerate(paragraphs, 1)
        ]
        return blocks or [BlockDraft("paragraph:1", 1, "paragraph", content.strip())]

    value = contract_model.model_validate_json(content)

    def add(key: str, kind: str, text: str, **metadata: object) -> None:
        candidate = _block(key, kind, text, **metadata)
        if candidate is not None:
            blocks.append(candidate)

    if isinstance(value, PresentationSpec):
        add("deck:title", "title", value.title, field="title")
        for slide_index, slide in enumerate(value.slides, 1):
            prefix = f"slide:{slide_index}"
            add(f"{prefix}:title", "title", slide.title, slide=slide_index, field="title")
            add(
                f"{prefix}:key_message",
                "key_message",
                slide.key_message,
                slide=slide_index,
                field="key_message",
            )
            for bullet_index, bullet in enumerate(slide.bullets, 1):
                add(
                    f"{prefix}:bullet:{bullet_index}",
                    "bullet",
                    bullet,
                    slide=slide_index,
                    field="bullets",
                    item=bullet_index,
                )
            add(
                f"{prefix}:speaker_notes",
                "speaker_notes",
                slide.speaker_notes,
                slide=slide_index,
                field="speaker_notes",
            )
            add(
                f"{prefix}:visual_recommendation",
                "visual_direction",
                slide.visual_recommendation,
                slide=slide_index,
                field="visual_recommendation",
            )
    elif isinstance(value, InfographicSpec):
        add("infographic:title", "title", value.title, field="title")
        add("infographic:subtitle", "subtitle", value.subtitle, field="subtitle")
        add("infographic:key_message", "key_message", value.key_message, field="key_message")
        for block_index, item in enumerate(value.blocks, 1):
            prefix = f"block:{block_index}"
            if isinstance(item, InfographicSectionBlock):
                add(f"{prefix}:heading", "heading", item.heading, block=block_index)
                add(f"{prefix}:body", "body", item.body, block=block_index)
            elif isinstance(item, InfographicCalloutBlock):
                add(f"{prefix}:label", "callout_label", item.label, block=block_index)
                add(f"{prefix}:value", "callout_value", item.value, block=block_index)
                add(
                    f"{prefix}:explanation",
                    "callout_explanation",
                    item.explanation,
                    block=block_index,
                )
            else:
                add(f"{prefix}:heading", "heading", item.heading, block=block_index)
                for row_index, row in enumerate(item.rows, 1):
                    row_prefix = f"{prefix}:row:{row_index}"
                    add(
                        f"{row_prefix}:label",
                        "data_label",
                        row.label,
                        block=block_index,
                        row=row_index,
                    )
                    add(
                        f"{row_prefix}:value",
                        "data_value",
                        row.value,
                        block=block_index,
                        row=row_index,
                    )
                    add(
                        f"{row_prefix}:note",
                        "data_note",
                        row.note,
                        block=block_index,
                        row=row_index,
                    )
        add("infographic:visual_direction", "visual_direction", value.visual_direction)
    else:
        add("video:title", "title", value.title, field="title")
        add("video:concept", "concept", value.concept, field="concept")
        for scene_index, scene in enumerate(value.scenes, 1):
            prefix = f"scene:{scene_index}"
            add(f"{prefix}:title", "title", scene.title, scene=scene_index, field="title")
            add(
                f"{prefix}:narration",
                "narration",
                scene.narration,
                scene=scene_index,
                field="narration",
            )
            for line_index, line in enumerate(scene.on_screen_text, 1):
                add(
                    f"{prefix}:on_screen:{line_index}",
                    "on_screen_text",
                    line,
                    scene=scene_index,
                    item=line_index,
                )
            add(
                f"{prefix}:visual_direction",
                "visual_direction",
                scene.visual_direction,
                scene=scene_index,
                field="visual_direction",
            )
            add(
                f"{prefix}:transition_notes",
                "transition_notes",
                scene.transition_notes,
                scene=scene_index,
                field="transition_notes",
            )

    return [
        BlockDraft(
            item.block_key,
            ordinal,
            item.block_type,
            item.visible_text,
            item.structural_metadata,
        )
        for ordinal, item in enumerate(blocks, 1)
    ]


def persist_artifact_blocks(
    session: Session,
    artifact_version: ArtifactVersion,
    output_type: OutputType,
    *,
    parent_version: ArtifactVersion | None = None,
    origin: str,
) -> list[ArtifactBlock]:
    """Create version blocks and carry only exact-key, exact-content parent dependencies."""
    drafts = extract_artifact_blocks(output_type, artifact_version.content)
    created = [
        ArtifactBlock(
            artifact_version_id=artifact_version.id,
            block_key=draft.block_key,
            ordinal=draft.ordinal,
            block_type=draft.block_type,
            visible_text=draft.visible_text,
            content_hash=draft.content_hash,
            structural_metadata=draft.structural_metadata,
            created_at=utc_now(),
        )
        for draft in drafts
    ]
    session.add_all(created)
    session.flush()

    if parent_version is not None:
        parents = {
            block.block_key: block
            for block in session.scalars(
                select(ArtifactBlock).where(ArtifactBlock.artifact_version_id == parent_version.id)
            )
        }
        by_key = {block.block_key: block for block in created}
        source_version_changed = (
            parent_version.source_version_id != artifact_version.source_version_id
        )
        alignment_scope: tuple[int, int] | None = None
        if source_version_changed:
            parent_pack_version_id = session.scalar(
                select(SourcePackVersion.id).where(
                    SourcePackVersion.source_version_id == parent_version.source_version_id
                )
            )
            child_pack_version_id = session.scalar(
                select(SourcePackVersion.id).where(
                    SourcePackVersion.source_version_id == artifact_version.source_version_id
                )
            )
            if parent_pack_version_id is not None and child_pack_version_id is not None:
                alignment_scope = (parent_pack_version_id, child_pack_version_id)
        for key, parent in parents.items():
            child = by_key.get(key)
            if child is None or child.content_hash != parent.content_hash:
                continue
            old_dependencies = list(
                session.scalars(
                    select(ArtifactBlockDependency).where(
                        ArtifactBlockDependency.artifact_block_id == parent.id
                    )
                )
            )
            if not source_version_changed:
                session.add_all(
                    ArtifactBlockDependency(
                        artifact_block_id=child.id,
                        source_region_id=dependency.source_region_id,
                        knowledge_assertion_id=dependency.knowledge_assertion_id,
                        source_content_hash=dependency.source_content_hash,
                        dependency_hash=dependency.dependency_hash,
                        dependency_kind=dependency.dependency_kind,
                        origin="carried_forward",
                        profile_version=dependency.profile_version,
                        created_at=utc_now(),
                    )
                    for dependency in old_dependencies
                )
                continue
            if alignment_scope is None:
                continue
            parent_pack_version_id, child_pack_version_id = alignment_scope
            for dependency in old_dependencies:
                alignments = list(
                    session.scalars(
                        select(SourceRegionAlignment).where(
                            SourceRegionAlignment.parent_pack_version_id == parent_pack_version_id,
                            SourceRegionAlignment.child_pack_version_id == child_pack_version_id,
                            SourceRegionAlignment.old_region_id == dependency.source_region_id,
                            SourceRegionAlignment.alignment_state.in_(("unchanged", "moved")),
                        )
                    )
                )
                if len(alignments) != 1 or alignments[0].new_region_id is None:
                    continue
                new_region = session.get(SourceRegion, alignments[0].new_region_id)
                if new_region is None or new_region.text is None:
                    continue
                new_source_hash = sha256(new_region.text.encode("utf-8")).hexdigest()
                if new_source_hash != dependency.source_content_hash:
                    continue
                add_validated_dependency(
                    session,
                    child,
                    new_region,
                    assertion=None,
                    dependency_kind="quote",
                    origin="carried_forward",
                    profile_version=dependency.profile_version,
                )
    return created


def add_validated_dependency(
    session: Session,
    block: ArtifactBlock,
    region: SourceRegion,
    *,
    assertion: KnowledgeAssertion | None,
    dependency_kind: str,
    origin: str,
    profile_version: str,
) -> ArtifactBlockDependency:
    """Create a dependency only after caller has independently validated its provenance."""
    if region.text is None:
        raise ValueError("A dependency requires an addressable source region")
    asset = session.get(SourceAsset, region.source_asset_id)
    if asset is None:
        raise ValueError("The source region asset is unavailable")
    source_hash = sha256(region.text.encode("utf-8")).hexdigest()
    hash_input = json.dumps(
        {
            "source_region_id": region.id,
            "source_pack_version_id": asset.source_pack_version_id,
            "source_content_hash": source_hash,
            "artifact_block_hash": block.content_hash,
            "profile_version": profile_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    dependency_hash = sha256(hash_input.encode("utf-8")).hexdigest()
    row = session.scalar(
        select(ArtifactBlockDependency).where(
            ArtifactBlockDependency.artifact_block_id == block.id,
            ArtifactBlockDependency.source_region_id == region.id,
            ArtifactBlockDependency.dependency_hash == dependency_hash,
        )
    )
    if row is None:
        row = ArtifactBlockDependency(
            artifact_block_id=block.id,
            source_region_id=region.id,
            knowledge_assertion_id=assertion.id if assertion is not None else None,
            source_content_hash=source_hash,
            dependency_hash=dependency_hash,
            dependency_kind=dependency_kind,
            origin=origin,
            profile_version=profile_version,
            created_at=utc_now(),
        )
        session.add(row)
    return row


def validate_and_store_lineage_proposals(
    session: Session,
    owner: User,
    artifact_version: ArtifactVersion,
    proposals: list[LineageProposalItem],
) -> list[LineageProposal]:
    """Persist raw proposals and independently validate IDs, scope, role, and exact spans."""
    artifact_run = session.get(ArtifactRun, artifact_version.artifact_run_id)
    transformation = (
        session.get(TransformationRun, artifact_run.transformation_run_id)
        if artifact_run is not None
        else None
    )
    manifest = (
        session.get(ContextManifest, artifact_version.context_manifest_id)
        if artifact_version.context_manifest_id is not None
        else None
    )
    if (
        transformation is None
        or transformation.owner_id != owner.id
        or manifest is None
        or manifest.owner_id != owner.id
        or manifest.source_version_id != artifact_version.source_version_id
    ):
        raise ValueError("Lineage proposals require the exact owned artifact ContextManifest")

    blocks = {
        block.block_key: block
        for block in session.scalars(
            select(ArtifactBlock).where(ArtifactBlock.artifact_version_id == artifact_version.id)
        )
    }
    stored: list[LineageProposal] = []
    for candidate in proposals:
        block = blocks.get(candidate.block_key)
        state: Literal[
            "validated",
            "invalid_scope",
            "invalid_region",
            "invalid_assertion",
            "invalid_span",
            "ambiguous",
            "unresolved",
        ] = "unresolved"
        reason: str | None = None
        region: SourceRegion | None = None
        assertion: KnowledgeAssertion | None = None
        quote_start: int | None = None
        quote_end: int | None = None

        if block is None:
            reason = "block_not_in_artifact_version"
        elif candidate.source_region_id is None:
            reason = "source_region_not_proposed"
        else:
            region_row = session.execute(
                select(
                    SourceRegion,
                    ContextManifestEntry,
                    SourcePackMembership,
                    SourcePack,
                    SourceVersion,
                    Source,
                )
                .join(
                    ContextManifestEntry, ContextManifestEntry.source_region_id == SourceRegion.id
                )
                .join(
                    SourcePackMembership,
                    SourcePackMembership.id == ContextManifestEntry.membership_id,
                )
                .join(
                    SourcePackVersion,
                    SourcePackVersion.id == SourcePackMembership.source_pack_version_id,
                )
                .join(SourcePack, SourcePack.id == SourcePackVersion.source_pack_id)
                .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
                .join(Source, Source.id == SourceVersion.source_id)
                .where(
                    SourceRegion.id == candidate.source_region_id,
                    ContextManifestEntry.context_manifest_id == manifest.id,
                    ContextManifestEntry.selected.is_(True),
                    SourcePackVersion.id == manifest.source_pack_version_id,
                    SourcePack.owner_id == owner.id,
                    Source.owner_id == owner.id,
                )
            ).one_or_none()
            if region_row is None:
                region_exists = session.get(SourceRegion, candidate.source_region_id)
                state = "invalid_scope" if region_exists is not None else "invalid_region"
                reason = "region_not_owned_or_not_in_selected_manifest"
            else:
                region, entry, membership, _pack, _source_version, _source = region_row
                if entry.role not in {"PRIMARY", "SUPPORTING"} or membership.role != entry.role:
                    state, reason = "invalid_scope", "source_role_not_allowed"
                elif region.text is None or not candidate.source_quote:
                    state, reason = "invalid_span", "quote_missing_or_region_unaddressable"
                else:
                    starts: list[int]
                    if candidate.quote_start is not None or candidate.quote_end is not None:
                        start, end = candidate.quote_start, candidate.quote_end
                        exact = (
                            start is not None
                            and end is not None
                            and 0 <= start < end <= len(region.text)
                            and region.text[start:end] == candidate.source_quote
                        )
                        starts = [start] if exact and start is not None else []
                    else:
                        starts = []
                        offset = 0
                        while (found := region.text.find(candidate.source_quote, offset)) >= 0:
                            starts.append(found)
                            offset = found + 1
                    if len(starts) == 1:
                        quote_start = starts[0]
                        quote_end = quote_start + len(candidate.source_quote)
                    elif len(starts) > 1:
                        state, reason = "ambiguous", "quote_occurs_multiple_times_in_region"
                    else:
                        state, reason = "invalid_span", "quote_does_not_match_exact_offsets"

                    if (
                        state not in {"ambiguous", "invalid_span"}
                        and candidate.knowledge_assertion_id is not None
                    ):
                        assertion = session.get(
                            KnowledgeAssertion, candidate.knowledge_assertion_id
                        )
                        if (
                            assertion is None
                            or assertion.owner_id != owner.id
                            or assertion.source_pack_version_id != manifest.source_pack_version_id
                            or assertion.source_region_id != region.id
                            or assertion.provenance_state != "validated"
                            or assertion.source_quote is None
                            or assertion.quote_start is None
                            or assertion.quote_end is None
                            or region.text[assertion.quote_start : assertion.quote_end]
                            != assertion.source_quote
                        ):
                            assertion = None
                            state, reason = "invalid_assertion", "assertion_scope_or_span_mismatch"
                    if state not in {"ambiguous", "invalid_span", "invalid_assertion"}:
                        state, reason = "validated", None

        record = LineageProposal(
            owner_id=owner.id,
            artifact_version_id=artifact_version.id,
            artifact_block_id=block.id if block is not None else None,
            proposed_block_key=candidate.block_key,
            proposed_claim=candidate.claim_text,
            proposed_source_region_id=candidate.source_region_id,
            proposed_assertion_id=candidate.knowledge_assertion_id,
            proposed_quote=candidate.source_quote,
            proposed_quote_start=candidate.quote_start,
            proposed_quote_end=candidate.quote_end,
            validated_quote_start=quote_start if state == "validated" else None,
            validated_quote_end=quote_end if state == "validated" else None,
            validation_state=state,
            rejection_reason=reason,
            proposal_profile=LINEAGE_PROPOSAL_PROFILE,
            proposal_profile_version=LINEAGE_PROPOSAL_PROFILE_VERSION,
            created_at=utc_now(),
        )
        session.add(record)
        session.flush()
        if state == "validated" and block is not None and region is not None:
            add_validated_dependency(
                session,
                block,
                region,
                assertion=assertion,
                dependency_kind="assertion" if assertion is not None else "quote",
                origin="proposal",
                profile_version=f"{LINEAGE_PROPOSAL_PROFILE}:{LINEAGE_PROPOSAL_PROFILE_VERSION}",
            )
        stored.append(record)
    return stored


def reconcile_claim_block(
    session: Session, claim: MaterialClaim, artifact_version: ArtifactVersion
) -> str:
    """Link a validated claim span only when its quotation maps to exactly one block."""
    if claim.artifact_start >= claim.artifact_end or not claim.artifact_quote:
        return "ambiguous"
    blocks = list(
        session.scalars(
            select(ArtifactBlock).where(ArtifactBlock.artifact_version_id == artifact_version.id)
        )
    )
    matches = [block for block in blocks if claim.artifact_quote in block.visible_text]
    state = "validated" if len(matches) == 1 else "ambiguous"
    claim.block_mapping_state = state
    for block in matches:
        exists = session.scalar(
            select(MaterialClaimBlock.id).where(
                MaterialClaimBlock.material_claim_id == claim.id,
                MaterialClaimBlock.artifact_block_id == block.id,
            )
        )
        if exists is None:
            session.add(
                MaterialClaimBlock(
                    material_claim_id=claim.id,
                    artifact_block_id=block.id,
                    mapping_state=state,
                    created_at=utc_now(),
                )
            )
    return state


def reconcile_lineage_claims(session: Session, artifact_version: ArtifactVersion) -> None:
    """Attach a validated proposal to a claim only on exact proposition and block matches."""
    scan_ids = list(
        session.scalars(
            select(ClaimScan.id).where(ClaimScan.artifact_version_id == artifact_version.id)
        )
    )
    if not scan_ids:
        return
    mapped_rows = session.execute(
        select(
            MaterialClaim, MaterialClaimBlock.artifact_block_id, MaterialClaimBlock.mapping_state
        )
        .join(MaterialClaimBlock, MaterialClaimBlock.material_claim_id == MaterialClaim.id)
        .where(MaterialClaim.claim_scan_id.in_(scan_ids))
    ).all()
    claims_by_block_and_text: dict[tuple[int, str], list[tuple[MaterialClaim, str]]] = {}
    for claim, block_id, mapping_state in mapped_rows:
        claims_by_block_and_text.setdefault((block_id, claim.normalized_hash), []).append(
            (claim, mapping_state)
        )

    proposals = list(
        session.scalars(
            select(LineageProposal)
            .where(LineageProposal.artifact_version_id == artifact_version.id)
            .order_by(LineageProposal.id)
        )
    )
    possible_matches: dict[int, list[LineageProposal]] = {}
    for proposal in proposals:
        proposal.material_claim_id = None
        if proposal.validation_state != "validated" or proposal.artifact_block_id is None:
            continue
        normalized_hash = sha256(
            " ".join(proposal.proposed_claim.casefold().split()).encode()
        ).hexdigest()
        matches = claims_by_block_and_text.get((proposal.artifact_block_id, normalized_hash), [])
        safe_matches = [
            claim
            for claim, mapping_state in matches
            if mapping_state == "validated" and claim.block_mapping_state == "validated"
        ]
        if len(safe_matches) == 1 and len(matches) == 1:
            possible_matches.setdefault(safe_matches[0].id, []).append(proposal)
        elif matches:
            proposal.validation_state = "ambiguous"
            proposal.rejection_reason = "material_claim_mapping_ambiguous"

    for claim_id, matched_proposals in possible_matches.items():
        if len(matched_proposals) == 1:
            matched_proposals[0].material_claim_id = claim_id
        else:
            for proposal in matched_proposals:
                proposal.validation_state = "ambiguous"
                proposal.rejection_reason = "multiple_lineage_proposals_match_material_claim"


def block_inventory_covers_projection(output_type: OutputType, content: str) -> bool:
    """Check every non-empty addressable field is represented in the block inventory."""
    projection = artifact_text_projection(output_type, content)
    blocks = extract_artifact_blocks(output_type, content)
    if not projection.strip() or not blocks:
        return False
    return all(draft.visible_text in projection for draft in blocks)


def replace_artifact_blocks(
    output_type: OutputType,
    content: str,
    allowed_block_keys: list[str],
    replacements: dict[str, str],
) -> str:
    """Apply only server-authorized block replacements and validate the family contract."""
    if not allowed_block_keys or len(allowed_block_keys) != len(set(allowed_block_keys)):
        raise ValueError("Selective revision requires unique authorized block keys")
    if set(replacements) != set(allowed_block_keys):
        raise ValueError("Selective revision replacement keys do not match the authorized set")
    if any(not text.strip() for text in replacements.values()):
        raise ValueError("Selective revision replacements must contain visible text")

    drafts = extract_artifact_blocks(output_type, content)
    by_key = {draft.block_key: draft for draft in drafts}
    if any(key not in by_key for key in allowed_block_keys):
        raise ValueError("An authorized block does not exist in the base artifact")

    model = {
        OutputType.PRESENTATION: PresentationSpec,
        OutputType.INFOGRAPHIC: InfographicSpec,
        OutputType.VIDEO_PACKAGE: VideoPackageSpec,
    }.get(output_type)
    if model is None:
        parts = re.split(r"(\n\s*\n)", content.strip())
        paragraph_index = 0
        for index in range(0, len(parts), 2):
            if parts[index].strip():
                paragraph_index += 1
                key = f"paragraph:{paragraph_index}"
                if key in replacements:
                    parts[index] = replacements[key]
        return validate_artifact_content(output_type, "".join(parts))

    value = model.model_validate_json(content).model_dump(mode="json")
    for key, replacement in replacements.items():
        if output_type == OutputType.PRESENTATION:
            if key == "deck:title":
                value["title"] = replacement
                continue
            match = re.fullmatch(
                r"slide:(\d+):(title|key_message|speaker_notes|visual_recommendation)", key
            )
            bullet_match = re.fullmatch(r"slide:(\d+):bullet:(\d+)", key)
            if match:
                slide_index = int(match.group(1)) - 1
                if not 0 <= slide_index < len(value["slides"]):
                    raise ValueError("Slide block no longer exists")
                value["slides"][slide_index][match.group(2)] = replacement
            elif bullet_match:
                slide_index, bullet_index = (
                    int(bullet_match.group(1)) - 1,
                    int(bullet_match.group(2)) - 1,
                )
                if not 0 <= slide_index < len(value["slides"]) or not 0 <= bullet_index < len(
                    value["slides"][slide_index]["bullets"]
                ):
                    raise ValueError("Bullet block no longer exists")
                value["slides"][slide_index]["bullets"][bullet_index] = replacement
            else:
                raise ValueError("Unknown presentation block key")
        elif output_type == OutputType.INFOGRAPHIC:
            if key.startswith("infographic:"):
                field = key.removeprefix("infographic:")
                if field not in {"title", "subtitle", "key_message", "visual_direction"}:
                    raise ValueError("Unknown infographic block key")
                value[field] = replacement
                continue
            match = re.fullmatch(r"block:(\d+):(heading|body|label|value|explanation)", key)
            row_match = re.fullmatch(r"block:(\d+):row:(\d+):(label|value|note)", key)
            if match:
                block_index = int(match.group(1)) - 1
                if not 0 <= block_index < len(value["blocks"]):
                    raise ValueError("Infographic block no longer exists")
                block = value["blocks"][block_index]
                field = match.group(2)
                if field in {"heading", "body"} and block["type"] in {"section", "data"}:
                    block[field] = replacement
                elif field in {"label", "value", "explanation"} and block["type"] == "callout":
                    block[field] = replacement
                else:
                    raise ValueError("Infographic block type changed")
            elif row_match:
                block_index, row_index = int(row_match.group(1)) - 1, int(row_match.group(2)) - 1
                if not 0 <= block_index < len(value["blocks"]):
                    raise ValueError("Infographic block no longer exists")
                block = value["blocks"][block_index]
                if block["type"] != "data" or not 0 <= row_index < len(block["rows"]):
                    raise ValueError("Infographic data row no longer exists")
                block["rows"][row_index][row_match.group(3)] = replacement
            else:
                raise ValueError("Unknown infographic block key")
        else:
            if key in {"video:title", "video:concept"}:
                value[key.removeprefix("video:")] = replacement
                continue
            match = re.fullmatch(
                r"scene:(\d+):(title|narration|visual_direction|transition_notes)", key
            )
            text_match = re.fullmatch(r"scene:(\d+):on_screen:(\d+)", key)
            if match:
                scene_index = int(match.group(1)) - 1
                if not 0 <= scene_index < len(value["scenes"]):
                    raise ValueError("Video scene no longer exists")
                value["scenes"][scene_index][match.group(2)] = replacement
            elif text_match:
                scene_index, line_index = int(text_match.group(1)) - 1, int(text_match.group(2)) - 1
                if not 0 <= scene_index < len(value["scenes"]) or not 0 <= line_index < len(
                    value["scenes"][scene_index]["on_screen_text"]
                ):
                    raise ValueError("On-screen text block no longer exists")
                value["scenes"][scene_index]["on_screen_text"][line_index] = replacement
            else:
                raise ValueError("Unknown video block key")
    return validate_artifact_content(output_type, json.dumps(value, ensure_ascii=False))
