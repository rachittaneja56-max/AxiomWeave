"""Small PostgreSQL retrieval boundary for Phase 2 candidate profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from sqlalchemy import bindparam, func, literal_column, select, text
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.context_planning import (
    AVAILABLE_INPUT_BUDGET,
    CONTEXT_BUDGET_POLICY_VERSION,
    CONTEXT_BUDGET_UNITS,
    CONTEXT_ESTIMATION_METHOD,
    RESERVED_OUTPUT_SCHEMA_EVIDENCE_MARGIN,
)
from app.models import (
    ContextManifest,
    ContextManifestEntry,
    RegionEmbedding,
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceVersion,
    TextEmbeddingProfile,
    utc_now,
)

FACTUAL_ROLES = ("PRIMARY", "SUPPORTING")
RRF_PROFILE = "rrf-k60-v1"
RRF_K = 60


@dataclass(frozen=True, slots=True)
class RetrievalProfile:
    name: str
    version: int
    disposition: str
    quality_status: str


RETRIEVAL_PROFILES = {
    "postgres_fts": RetrievalProfile("postgres_fts", 1, "CANDIDATE", "NOT_PROMOTED"),
    "exact_vector": RetrievalProfile("exact_vector", 1, "MECHANICS_ONLY", "NOT_EVALUATED"),
    "hybrid_rrf": RetrievalProfile("hybrid_rrf", 1, "MECHANICS_ONLY", "NOT_EVALUATED"),
}


@dataclass(frozen=True, slots=True)
class RankedRegion:
    source_region_id: int
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class FusedRegion:
    source_region_id: int
    lexical_rank: int | None
    lexical_score: float | None
    vector_rank: int | None
    vector_score: float | None
    fused_rank: int
    fused_score: float


class TextEmbeddingProvider(Protocol):
    """Minimal provider capability; no production profile is selected in Phase 2."""

    def embed(self, texts: list[str], profile: TextEmbeddingProfile) -> list[list[float]]: ...


class PostgresRetrievalRepository:
    """Native PostgreSQL FTS and exact pgvector search, always owner/version/role scoped."""

    def search_fts(
        self,
        session: Session,
        *,
        owner_id: int,
        source_pack_version_id: int,
        query: str,
        roles: tuple[str, ...] = FACTUAL_ROLES,
        limit: int = 45,
    ) -> list[RankedRegion]:
        _validate_search(session, query, roles, limit)
        if session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("retrieval_requires_postgresql")
        config: ColumnElement[Any] = literal_column("'simple'::regconfig")
        query_vector = func.plainto_tsquery(config, query.strip())
        document_vector = func.to_tsvector(
            config, func.coalesce(SourceRegion.text, literal_column("''"))
        )
        rank = func.ts_rank_cd(document_vector, query_vector)
        asset_pack_version = aliased(SourcePackVersion)
        statement = (
            select(SourceRegion.id, rank.label("rank_score"))
            .join(SourceAsset, SourceAsset.id == SourceRegion.source_asset_id)
            .join(asset_pack_version, asset_pack_version.id == SourceAsset.source_pack_version_id)
            .join(SourcePackMembership, SourcePackMembership.source_asset_id == SourceAsset.id)
            .join(
                SourcePackVersion,
                SourcePackVersion.id == SourcePackMembership.source_pack_version_id,
            )
            .join(SourcePack, SourcePack.id == SourcePackVersion.source_pack_id)
            .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                SourcePack.owner_id == owner_id,
                Source.owner_id == owner_id,
                SourcePackVersion.id == source_pack_version_id,
                SourcePackMembership.source_pack_version_id == source_pack_version_id,
                asset_pack_version.source_version_id == SourcePackMembership.source_version_id,
                SourcePackMembership.role.in_(roles),
                SourceAsset.extraction_coverage == "complete",
                SourceRegion.text.is_not(None),
                document_vector.op("@@")(query_vector),
            )
            .order_by(
                rank.desc(), SourcePackMembership.ordinal, SourceRegion.ordinal, SourceRegion.id
            )
            .limit(limit)
        )
        rows = session.execute(statement).all()
        return [
            RankedRegion(int(row.id), ordinal, float(row.rank_score))
            for ordinal, row in enumerate(rows, 1)
        ]

    def search_exact_vector(
        self,
        session: Session,
        *,
        owner_id: int,
        source_pack_version_id: int,
        embedding_profile_id: int,
        query_vector: list[float],
        roles: tuple[str, ...] = FACTUAL_ROLES,
        limit: int = 45,
    ) -> list[RankedRegion]:
        _validate_roles(roles)
        if not 1 <= limit <= 100:
            raise ValueError("Retrieval limit must be between 1 and 100")
        if session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("retrieval_requires_postgresql")
        profile = session.get(TextEmbeddingProfile, embedding_profile_id)
        if profile is None or len(query_vector) != profile.dimension:
            raise ValueError("Embedding profile and query dimension do not match")
        if not all(math.isfinite(value) for value in query_vector):
            raise ValueError("Embedding vector values must be finite")
        encoded = "[" + ",".join(format(value, ".9g") for value in query_vector) + "]"
        statement = text(
            "SELECT r.id AS region_id, e.source_content_hash, r.text, "
            "e.embedding <=> CAST(:query_vector AS vector) AS distance "
            "FROM region_embeddings AS e "
            "JOIN source_regions AS r ON r.id = e.source_region_id "
            "JOIN source_assets AS a ON a.id = r.source_asset_id "
            "JOIN source_pack_memberships AS m ON m.source_asset_id = a.id "
            "JOIN source_pack_versions AS pv ON pv.id = m.source_pack_version_id "
            "JOIN source_pack_versions AS apv ON apv.id = a.source_pack_version_id "
            "JOIN source_packs AS p ON p.id = pv.source_pack_id "
            "JOIN source_versions AS sv ON sv.id = m.source_version_id "
            "JOIN sources AS s ON s.id = sv.source_id "
            "WHERE p.owner_id = :owner_id AND s.owner_id = :owner_id "
            "AND pv.id = :pack_version_id AND m.source_pack_version_id = :pack_version_id "
            "AND apv.source_version_id = m.source_version_id AND m.role IN :roles "
            "AND a.extraction_coverage = 'complete' AND r.text IS NOT NULL "
            "AND e.embedding_profile_id = :profile_id "
            "ORDER BY e.embedding <=> CAST(:query_vector AS vector), "
            "m.ordinal, r.ordinal, r.id"
        ).bindparams(bindparam("roles", expanding=True))
        rows = session.execute(
            statement,
            {
                "query_vector": encoded,
                "owner_id": owner_id,
                "pack_version_id": source_pack_version_id,
                "profile_id": embedding_profile_id,
                "roles": list(roles),
            },
        ).mappings()
        valid: list[tuple[int, float]] = []
        for row in rows:
            exact_hash = sha256((row["text"] or "").encode("utf-8")).hexdigest()
            if exact_hash != row["source_content_hash"]:
                continue
            valid.append((int(row["region_id"]), float(row["distance"])))
        valid = valid[:limit]
        return [
            RankedRegion(region_id, ordinal, distance)
            for ordinal, (region_id, distance) in enumerate(valid, 1)
        ]


def fuse_reciprocal_ranks(
    lexical: list[RankedRegion], vector: list[RankedRegion]
) -> list[FusedRegion]:
    """Fixed rank-only fusion avoids adding incomparable FTS and cosine scores."""
    lexical_by_region = {item.source_region_id: item for item in lexical}
    vector_by_region = {item.source_region_id: item for item in vector}
    all_region_ids = set(lexical_by_region) | set(vector_by_region)
    fused_values: list[FusedRegion] = []
    for region_id in all_region_ids:
        lexical_item = lexical_by_region.get(region_id)
        vector_item = vector_by_region.get(region_id)
        fused_score = sum(
            1 / (RRF_K + item.rank) for item in (lexical_item, vector_item) if item is not None
        )
        fused_values.append(
            FusedRegion(
                source_region_id=region_id,
                lexical_rank=lexical_item.rank if lexical_item else None,
                lexical_score=lexical_item.score if lexical_item else None,
                vector_rank=vector_item.rank if vector_item else None,
                vector_score=vector_item.score if vector_item else None,
                fused_rank=0,
                fused_score=fused_score,
            )
        )
    ordered = sorted(fused_values, key=lambda item: (-item.fused_score, item.source_region_id))
    return [
        FusedRegion(
            source_region_id=item.source_region_id,
            lexical_rank=item.lexical_rank,
            lexical_score=item.lexical_score,
            vector_rank=item.vector_rank,
            vector_score=item.vector_score,
            fused_rank=ordinal,
            fused_score=item.fused_score,
        )
        for ordinal, item in enumerate(ordered, 1)
    ]


def store_region_embedding(
    session: Session,
    region: SourceRegion,
    profile: TextEmbeddingProfile,
    vector: list[float],
) -> RegionEmbedding:
    """Persist only an exact profile/dimension/content dependency match."""
    if region.text is None or len(vector) != profile.dimension:
        raise ValueError("Embedding input does not match the exact profile dimension")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding vector values must be finite")
    content_hash = sha256(region.text.encode("utf-8")).hexdigest()
    stored = session.scalar(
        select(RegionEmbedding).where(
            RegionEmbedding.source_region_id == region.id,
            RegionEmbedding.embedding_profile_id == profile.id,
        )
    )
    if stored is None:
        stored = RegionEmbedding(
            source_region_id=region.id,
            embedding_profile_id=profile.id,
            source_content_hash=content_hash,
            embedding=vector,
            created_at=utc_now(),
        )
        session.add(stored)
    else:
        stored.source_content_hash = content_hash
        stored.embedding = vector
        stored.created_at = utc_now()
    session.flush()
    return stored


def create_candidate_manifest(
    session: Session,
    *,
    owner_id: int,
    source_pack_id: int,
    source_pack_version_id: int,
    source_version_id: int,
    task_class: str,
    artifact_family: str,
    profile_name: str,
    query: str,
    lexical: list[RankedRegion],
    vector: list[RankedRegion],
    limit: int = 45,
) -> ContextManifest:
    """Freeze an inspectable R1 candidate without admitting it to generation."""
    if profile_name not in RETRIEVAL_PROFILES:
        raise ValueError("Retrieval profiles are code-owned and versioned")
    if not 1 <= limit <= 100:
        raise ValueError("Candidate limit must be between 1 and 100")
    profile = RETRIEVAL_PROFILES[profile_name]
    if profile_name == "postgres_fts":
        ranked = fuse_reciprocal_ranks(lexical, [])
    elif profile_name == "exact_vector":
        ranked = fuse_reciprocal_ranks([], vector)
    else:
        ranked = fuse_reciprocal_ranks(lexical, vector)
    selected_by_id = {item.source_region_id: item for item in ranked[:limit]}

    asset_pack_version = aliased(SourcePackVersion)
    rows = list(
        session.execute(
            select(SourcePackMembership, SourceAsset, SourceRegion)
            .join(SourceAsset, SourceAsset.id == SourcePackMembership.source_asset_id)
            .join(asset_pack_version, asset_pack_version.id == SourceAsset.source_pack_version_id)
            .join(SourceRegion, SourceRegion.source_asset_id == SourceAsset.id)
            .join(
                SourcePackVersion,
                SourcePackVersion.id == SourcePackMembership.source_pack_version_id,
            )
            .join(SourcePack, SourcePack.id == SourcePackVersion.source_pack_id)
            .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                SourcePack.owner_id == owner_id,
                Source.owner_id == owner_id,
                SourcePack.id == source_pack_id,
                SourcePackVersion.id == source_pack_version_id,
                SourcePackVersion.source_version_id == source_version_id,
                SourcePackMembership.source_pack_version_id == source_pack_version_id,
                asset_pack_version.source_version_id == SourcePackMembership.source_version_id,
                SourcePackMembership.role.in_(FACTUAL_ROLES),
                SourceAsset.extraction_coverage == "complete",
                SourceRegion.text.is_not(None),
            )
            .order_by(SourcePackMembership.ordinal, SourceRegion.ordinal, SourceRegion.id)
        ).all()
    )
    if not rows:
        raise ValueError("No complete eligible regions are available for an R1 candidate")
    route = {
        "postgres_fts": "R1_POSTGRES_FTS_CANDIDATE",
        "exact_vector": "R1_EXACT_VECTOR_CANDIDATE",
        "hybrid_rrf": "R1_HYBRID_CANDIDATE",
    }[profile_name]
    warnings = [f"profile_disposition:{profile.disposition}", "not_admitted_for_generation"]
    if profile_name in {"exact_vector", "hybrid_rrf"}:
        warnings.append("vector_quality_not_evaluated_no_approved_semantic_profile")
    estimated = sum(
        len(region.text or "")
        for _membership, _asset, region in rows
        if region.id in selected_by_id
    )
    manifest = ContextManifest(
        owner_id=owner_id,
        source_pack_id=source_pack_id,
        source_pack_version_id=source_pack_version_id,
        source_version_id=source_version_id,
        task_class=task_class,
        artifact_family=artifact_family,
        route=route,
        context_profile=profile.name,
        context_profile_version=profile.version,
        query_construction_version=1,
        query_text=query,
        budget_policy_version=CONTEXT_BUDGET_POLICY_VERSION,
        estimation_method=CONTEXT_ESTIMATION_METHOD,
        context_budget_units=CONTEXT_BUDGET_UNITS,
        available_input_budget=AVAILABLE_INPUT_BUDGET,
        estimated_context_units=estimated,
        reserved_margin=RESERVED_OUTPUT_SCHEMA_EVIDENCE_MARGIN,
        extraction_coverage="complete",
        state="candidate_only",
        warnings=warnings,
        created_at=utc_now(),
    )
    session.add(manifest)
    session.flush()
    for membership, asset, region in rows:
        result = selected_by_id.get(region.id)
        lexical_result = next(
            (item for item in lexical if item.source_region_id == region.id), None
        )
        vector_result = next((item for item in vector if item.source_region_id == region.id), None)
        fused_result = next((item for item in ranked if item.source_region_id == region.id), None)
        session.add(
            ContextManifestEntry(
                context_manifest_id=manifest.id,
                source_region_id=region.id,
                source_asset_id=asset.id,
                membership_id=membership.id,
                role=membership.role,
                selected=result is not None,
                candidate_rank=fused_result.fused_rank if fused_result else None,
                lexical_rank=lexical_result.rank if lexical_result else None,
                lexical_score=lexical_result.score if lexical_result else None,
                vector_rank=vector_result.rank if vector_result else None,
                vector_score=vector_result.score if vector_result else None,
                fused_rank=fused_result.fused_rank if fused_result else None,
                fused_score=fused_result.fused_score if fused_result else None,
                locator=region.locator,
                content_hash=sha256((region.text or "").encode("utf-8")).hexdigest(),
                estimated_context_units=len(region.text or ""),
                reason=(
                    "retrieval_candidate_selected" if result else "retrieval_candidate_omitted"
                ),
                profile_metadata={
                    "profile": profile.name,
                    "profile_version": profile.version,
                    "rank_fusion": RRF_PROFILE if profile_name == "hybrid_rrf" else None,
                },
            )
        )
    session.flush()
    return manifest


def _validate_search(session: Session, query: str, roles: tuple[str, ...], limit: int) -> None:
    _validate_roles(roles)
    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("retrieval_requires_postgresql")
    if not query.strip() or len(query) > 1_000:
        raise ValueError("Search query must contain 1 to 1,000 characters")
    if not 1 <= limit <= 100:
        raise ValueError("Retrieval limit must be between 1 and 100")


def _validate_roles(roles: tuple[str, ...]) -> None:
    if not roles or any(role not in FACTUAL_ROLES for role in roles):
        raise ValueError("Only PRIMARY and SUPPORTING regions may be factual candidates")
