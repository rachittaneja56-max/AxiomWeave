from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import (
    CreateTransformationRequest,
    PreparedTransformationRequest,
    TransformationRequest,
)
from app.models import Source, SourceSegment, TransformationRun, User
from app.source_versions import create_source_version

router = APIRouter()


@router.post("/transformations/prepare", response_model=PreparedTransformationRequest)
def prepare_transformation(
    transformation_request: TransformationRequest,
    _user: Annotated[User, Depends(require_current_user)],
) -> PreparedTransformationRequest:
    return PreparedTransformationRequest(request=transformation_request)


class SavedSourceVersion(BaseModel):
    id: int
    version_number: int
    content_hash: str
    segment_count: int


class SavedTransformation(BaseModel):
    status: Literal["saved"] = "saved"
    transformation_run_id: int
    source_id: int
    source_version: SavedSourceVersion
    output_types: list[str]


@router.post("/transformations", response_model=SavedTransformation)
def save_transformation(
    transformation_request: CreateTransformationRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> SavedTransformation:
    try:
        source = Source(owner_id=user.id)
        session.add(source)
        session.flush()
        source_version = create_source_version(session, source, transformation_request.source_text)
        session.flush()
        run = TransformationRun(
            owner_id=user.id,
            source_version_id=source_version.id,
            supporting_context=transformation_request.supporting_context,
            audience=transformation_request.audience,
            tone=transformation_request.tone,
            language=transformation_request.language,
            detail_level=transformation_request.detail_level,
            objective=transformation_request.objective,
            style=transformation_request.style,
            selected_output_types=[item.value for item in transformation_request.output_types],
        )
        session.add(run)
        session.flush()
        segment_count = (
            session.scalar(
                select(func.count())
                .select_from(SourceSegment)
                .where(SourceSegment.source_version_id == source_version.id)
            )
            or 0
        )
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "save_failed", "message": "The transformation could not be saved."},
        ) from None

    return SavedTransformation(
        transformation_run_id=run.id,
        source_id=source.id,
        source_version=SavedSourceVersion(
            id=source_version.id,
            version_number=source_version.version_number,
            content_hash=source_version.content_hash,
            segment_count=segment_count,
        ),
        output_types=[item.value for item in transformation_request.output_types],
    )
