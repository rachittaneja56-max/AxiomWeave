from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Source,
    SourceVersion,
    TransformationRun,
)


def get_owned_source(session: Session, owner_id: int, source_id: int) -> Source | None:
    return session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner_id))


def get_owned_source_version(
    session: Session, owner_id: int, source_version_id: int
) -> SourceVersion | None:
    return session.scalar(
        select(SourceVersion)
        .join(Source, SourceVersion.source_id == Source.id)
        .where(SourceVersion.id == source_version_id, Source.owner_id == owner_id)
    )


def get_owned_transformation_run(
    session: Session, owner_id: int, transformation_run_id: int
) -> TransformationRun | None:
    return session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == owner_id,
        )
    )


def get_owned_artifact_run(
    session: Session, owner_id: int, artifact_run_id: int
) -> ArtifactRun | None:
    return session.scalar(
        select(ArtifactRun)
        .join(
            TransformationRun,
            ArtifactRun.transformation_run_id == TransformationRun.id,
        )
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == owner_id)
    )


def get_owned_artifact_version(
    session: Session, owner_id: int, artifact_version_id: int
) -> ArtifactVersion | None:
    return session.scalar(
        select(ArtifactVersion)
        .join(ArtifactRun, ArtifactVersion.artifact_run_id == ArtifactRun.id)
        .join(TransformationRun, ArtifactRun.transformation_run_id == TransformationRun.id)
        .where(ArtifactVersion.id == artifact_version_id, TransformationRun.owner_id == owner_id)
    )
