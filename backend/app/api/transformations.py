from fastapi import APIRouter

from app.domain.transformation import PreparedTransformationRequest, TransformationRequest

router = APIRouter()


@router.post("/transformations/prepare", response_model=PreparedTransformationRequest)
def prepare_transformation(
    transformation_request: TransformationRequest,
) -> PreparedTransformationRequest:
    return PreparedTransformationRequest(request=transformation_request)
