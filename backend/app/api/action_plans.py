from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.action_planning import (
    create_action_plan,
    execute_action_plan,
    get_owned_transformation,
)
from app.action_planning import (
    reject_action_plan as reject_action_plan_workflow,
)
from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import SOURCE_TEXT_MAX_LENGTH
from app.models import (
    ActionPlan,
    ActionPlanStep,
    ChatMessage,
    User,
)
from app.rate_limits import rate_limit_dependency

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)


class GlobalChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    source_text: str | None = Field(default=None, max_length=SOURCE_TEXT_MAX_LENGTH)


class PlanDecisionRequest(BaseModel):
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_version: int = Field(gt=0)


class ActionPlanStepResponse(BaseModel):
    id: int
    ordinal: int
    command_type: str
    arguments: dict[str, object]
    target_ids: dict[str, int]
    summary: str
    consequential: bool
    status: str
    result_reference: str | None
    error_code: str | None


class ActionPlanResponse(BaseModel):
    id: int
    transformation_run_id: int | None
    explanation: str
    planner_profile: str
    planner_profile_version: str
    planner_model: str
    prompt_hash: str
    plan_hash: str
    plan_version: int
    requires_confirmation: bool
    status: str
    created_at: datetime
    execution_started_at: datetime | None
    executed_at: datetime | None
    steps: list[ActionPlanStepResponse]


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    action_plan_id: int | None
    created_at: datetime


class ChatWorkspaceResponse(BaseModel):
    messages: list[ChatMessageResponse]
    plans: list[ActionPlanResponse]


def _step_responses(session: Session, plan_id: int) -> list[ActionPlanStepResponse]:
    steps = session.scalars(
        select(ActionPlanStep)
        .where(ActionPlanStep.action_plan_id == plan_id)
        .order_by(ActionPlanStep.ordinal)
    ).all()
    return [
        ActionPlanStepResponse(
            id=step.id,
            ordinal=step.ordinal,
            command_type=step.command_type,
            arguments=step.arguments,
            target_ids=step.target_ids,
            summary=step.summary,
            consequential=step.consequential,
            status=step.status,
            result_reference=step.result_reference,
            error_code=step.error_code,
        )
        for step in steps
    ]


def _plan_response(session: Session, plan: ActionPlan) -> ActionPlanResponse:
    return ActionPlanResponse(
        id=plan.id,
        transformation_run_id=plan.transformation_run_id,
        explanation=plan.explanation,
        planner_profile=plan.planner_profile,
        planner_profile_version=plan.planner_profile_version,
        planner_model=plan.planner_model,
        prompt_hash=plan.prompt_hash,
        plan_hash=plan.plan_hash,
        plan_version=plan.plan_version,
        requires_confirmation=plan.requires_confirmation,
        status=plan.status,
        created_at=plan.created_at,
        execution_started_at=plan.execution_started_at,
        executed_at=plan.executed_at,
        steps=_step_responses(session, plan.id),
    )


@router.get("/weave/chat", response_model=ChatWorkspaceResponse)
def get_global_chat(
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ChatWorkspaceResponse:
    messages = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.owner_id == user.id, ChatMessage.transformation_run_id.is_(None))
        .order_by(ChatMessage.id.desc())
        .limit(100)
    ).all()
    plans = session.scalars(
        select(ActionPlan)
        .where(ActionPlan.owner_id == user.id, ActionPlan.transformation_run_id.is_(None))
        .order_by(ActionPlan.id.desc())
        .limit(20)
    ).all()
    return ChatWorkspaceResponse(
        messages=[
            ChatMessageResponse(
                id=item.id,
                role=item.role,
                content=item.content,
                action_plan_id=item.action_plan_id,
                created_at=item.created_at,
            )
            for item in reversed(messages)
        ],
        plans=[_plan_response(session, plan) for plan in reversed(plans)],
    )


@router.post(
    "/weave/chat",
    response_model=ActionPlanResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_dependency("action_planning", limit=12, window_seconds=60))],
)
async def propose_global_action_plan(
    body: GlobalChatRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ActionPlanResponse:
    plan = await create_action_plan(
        transformation_run_id=None,
        message=body.message,
        source_text=body.source_text,
        user=user,
        session=session,
    )
    return _plan_response(session, plan)


@router.get(
    "/transformations/{transformation_run_id}/chat",
    response_model=ChatWorkspaceResponse,
)
def get_chat_workspace(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ChatWorkspaceResponse:
    get_owned_transformation(session, user, transformation_run_id)
    messages = session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.owner_id == user.id,
            ChatMessage.transformation_run_id == transformation_run_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(100)
    ).all()
    plans = session.scalars(
        select(ActionPlan)
        .where(
            ActionPlan.owner_id == user.id,
            ActionPlan.transformation_run_id == transformation_run_id,
        )
        .order_by(ActionPlan.id.desc())
        .limit(20)
    ).all()
    return ChatWorkspaceResponse(
        messages=[
            ChatMessageResponse(
                id=item.id,
                role=item.role,
                content=item.content,
                action_plan_id=item.action_plan_id,
                created_at=item.created_at,
            )
            for item in reversed(messages)
        ],
        plans=[_plan_response(session, plan) for plan in reversed(plans)],
    )


@router.post(
    "/transformations/{transformation_run_id}/chat",
    response_model=ActionPlanResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_dependency("action_planning", limit=12, window_seconds=60))],
)
async def propose_action_plan(
    transformation_run_id: int,
    body: ChatRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ActionPlanResponse:
    plan = await create_action_plan(
        transformation_run_id=transformation_run_id,
        message=body.message,
        user=user,
        session=session,
    )
    return _plan_response(session, plan)


@router.post(
    "/action-plans/{action_plan_id}/confirm",
    response_model=ActionPlanResponse,
    dependencies=[Depends(rate_limit_dependency("action_execution", limit=30, window_seconds=60))],
)
async def confirm_action_plan(
    action_plan_id: int,
    body: PlanDecisionRequest,
    request: Request,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ActionPlanResponse:
    plan = await execute_action_plan(
        action_plan_id=action_plan_id,
        plan_hash=body.plan_hash,
        plan_version=body.plan_version,
        request_id=getattr(request.state, "request_id", None),
        user=user,
        session=session,
    )
    return _plan_response(session, plan)


@router.post("/action-plans/{action_plan_id}/reject", response_model=ActionPlanResponse)
def reject_action_plan(
    action_plan_id: int,
    body: PlanDecisionRequest,
    request: Request,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ActionPlanResponse:
    plan = reject_action_plan_workflow(
        action_plan_id=action_plan_id,
        plan_hash=body.plan_hash,
        plan_version=body.plan_version,
        request_id=getattr(request.state, "request_id", None),
        user=user,
        session=session,
    )
    return _plan_response(session, plan)
