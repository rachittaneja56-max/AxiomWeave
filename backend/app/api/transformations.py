from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_current_user
from app.domain.transformation import PreparedTransformationRequest, TransformationRequest
from app.models import User

router = APIRouter()


@router.post("/transformations/prepare", response_model=PreparedTransformationRequest)
def prepare_transformation(
    transformation_request: TransformationRequest,
    _user: Annotated[User, Depends(require_current_user)],
) -> PreparedTransformationRequest:
    return PreparedTransformationRequest(request=transformation_request)
