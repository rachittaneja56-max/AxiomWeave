from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode
from sqlalchemy.orm import Session

from app.audit import record_audit_event
from app.domain.transformation import CreateTransformationRequest, OutputType
from app.generation import StructuredGenerationProvider
from app.models import User


class GenerateSelectedArtifactsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["generate_selected_artifacts"] = "generate_selected_artifacts"
    transformation_run_id: int = Field(gt=0)


class RetryArtifactCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["retry_artifact"] = "retry_artifact"
    artifact_run_id: int = Field(gt=0)


class RegenerateArtifactCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["regenerate_artifact"] = "regenerate_artifact"
    artifact_run_id: int = Field(gt=0)


class TargetedUpdateArtifactCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["targeted_update_artifact"] = "targeted_update_artifact"
    artifact_run_id: int = Field(gt=0)


class AnalyzeArtifactEvidenceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["analyze_artifact_evidence"] = "analyze_artifact_evidence"
    artifact_version_id: int = Field(gt=0)


class SceneMediaAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scene_index: int = Field(ge=0, le=15)
    visual_asset_id: int | None = Field(default=None, gt=0)
    audio_asset_id: int | None = Field(default=None, gt=0)


class CreateMediaRenderCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["create_media_render"] = "create_media_render"
    artifact_version_id: int = Field(gt=0)
    scene_durations_ms: list[int | None] | None = Field(default=None, max_length=16)
    scene_media: list[SceneMediaAction] = Field(
        default_factory=list[SceneMediaAction], max_length=16
    )


class RetryFailedMediaTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["retry_failed_media_task"] = "retry_failed_media_task"
    render_id: int = Field(gt=0)


class ReviewMediaRenderCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["review_media_render"] = "review_media_render"
    render_id: int = Field(gt=0)
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class ReviewArtifactVersionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["review_artifact_version"] = "review_artifact_version"
    artifact_version_id: int = Field(gt=0)
    review_status: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=500)


EvidenceReviewState = Literal[
    "quote_located",
    "supported",
    "partial",
    "contradicted",
    "missing",
    "ambiguous",
    "conflict",
    "non_factual",
]


class CreateTransformationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["create_transformation"] = "create_transformation"
    request: CreateTransformationRequest


class CreateTransformationAndGenerateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_type: Literal["create_transformation_and_generate"] = (
        "create_transformation_and_generate"
    )
    request: CreateTransformationRequest


class CreatedArtifactRun(BaseModel):
    artifact_run_id: int
    output_type: OutputType
    status: Literal["pending", "running", "succeeded", "failed"]


class CreateTransformationAndGenerateResult(BaseModel):
    transformation_run_id: int
    source_version_id: int
    source_version_number: int
    generation_status: Literal["succeeded", "partial_failure", "running", "failed"]
    artifact_runs: list[CreatedArtifactRun]
    generation_error_code: str | None = None


class CreateSourceRevisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    transformation_run_id: int = Field(gt=0)
    source_text: str = Field(min_length=1, max_length=20_000)


class SaveArtifactVersionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_run_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=100_000)


class ReviewEvidenceAssessmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assessment_id: int = Field(gt=0)
    review_state: Literal["reviewed"] = "reviewed"
    adjudicated_state: EvidenceReviewState | None = None


class VerifyArtifactEvidenceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_version_id: int = Field(gt=0)


class ResumeClaimScanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_scan_id: int = Field(gt=0)


class AnalyzeSiblingConsistencyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_version_a_id: int = Field(gt=0)
    artifact_version_b_id: int = Field(gt=0)


class ReviewDiscrepancyFindingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    finding_id: int = Field(gt=0)
    review_status: Literal["dismissed"] = "dismissed"


class UpdateMediaAssetRightsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    asset_id: int = Field(gt=0)
    rights_basis: Literal[
        "user_owned", "permission_confirmed", "public_domain", "not_applicable", "unknown"
    ]
    consent_state: Literal["confirmed", "not_applicable", "unknown"]
    consent_required: bool = False
    attribution: str | None = Field(default=None, max_length=500)


class UpdateSourceAssetRightsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_asset_id: int = Field(gt=0)
    rights_basis: Literal[
        "user_owned", "permission_confirmed", "public_domain", "not_applicable", "unknown"
    ]
    consent_state: Literal["confirmed", "not_applicable", "unknown"]
    consent_required: bool = False
    attribution: str | None = Field(default=None, max_length=500)


type ManualApplicationCommand = (
    CreateTransformationCommand
    | CreateSourceRevisionCommand
    | SaveArtifactVersionCommand
    | ReviewEvidenceAssessmentCommand
    | VerifyArtifactEvidenceCommand
    | ResumeClaimScanCommand
    | AnalyzeSiblingConsistencyCommand
    | ReviewDiscrepancyFindingCommand
    | UpdateMediaAssetRightsCommand
    | UpdateSourceAssetRightsCommand
)


type ApplicationCommand = Annotated[
    CreateTransformationCommand
    | CreateTransformationAndGenerateCommand
    | GenerateSelectedArtifactsCommand
    | RetryArtifactCommand
    | RegenerateArtifactCommand
    | TargetedUpdateArtifactCommand
    | AnalyzeArtifactEvidenceCommand
    | CreateMediaRenderCommand
    | RetryFailedMediaTaskCommand
    | ReviewMediaRenderCommand
    | ReviewArtifactVersionCommand,
    Field(discriminator="command_type"),
]


class ProposedActionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: ApplicationCommand


class ActionPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(min_length=1, max_length=1_000)
    steps: list[ProposedActionStep] = Field(max_length=8)

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = "#/$defs/{model}",
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )

        def normalize_openai_keywords(node: object) -> None:
            if isinstance(node, dict):
                schema_node = cast(dict[str, object], node)
                if "const" in schema_node:
                    schema_node["enum"] = [schema_node.pop("const")]
                if "oneOf" in schema_node and "discriminator" in schema_node:
                    schema_node["anyOf"] = schema_node.pop("oneOf")
                    schema_node.pop("discriminator")
                for value in schema_node.values():
                    normalize_openai_keywords(value)
            elif isinstance(node, list):
                for value in cast(list[object], node):
                    normalize_openai_keywords(value)

        normalize_openai_keywords(schema)
        return schema


class CommandValidationError(ValueError):
    pass


COMMAND_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "create_transformation": CreateTransformationCommand,
    "create_transformation_and_generate": CreateTransformationAndGenerateCommand,
    "generate_selected_artifacts": GenerateSelectedArtifactsCommand,
    "retry_artifact": RetryArtifactCommand,
    "regenerate_artifact": RegenerateArtifactCommand,
    "targeted_update_artifact": TargetedUpdateArtifactCommand,
    "analyze_artifact_evidence": AnalyzeArtifactEvidenceCommand,
    "create_media_render": CreateMediaRenderCommand,
    "retry_failed_media_task": RetryFailedMediaTaskCommand,
    "review_media_render": ReviewMediaRenderCommand,
    "review_artifact_version": ReviewArtifactVersionCommand,
}


def parse_action_command(command_type: str, arguments: dict[str, object]) -> ApplicationCommand:
    model = COMMAND_ARGUMENT_MODELS.get(command_type)
    if model is None:
        raise CommandValidationError("unknown_command")
    if "command_type" in arguments:
        raise CommandValidationError("invalid_arguments")
    try:
        return model.model_validate({**arguments, "command_type": command_type})  # type: ignore[return-value]
    except ValidationError as error:
        raise CommandValidationError("invalid_arguments") from error


def command_targets(command: ApplicationCommand) -> dict[str, int]:
    if isinstance(command, (CreateTransformationCommand, CreateTransformationAndGenerateCommand)):
        return {}
    if isinstance(command, GenerateSelectedArtifactsCommand):
        return {"transformation_run_id": command.transformation_run_id}
    if isinstance(
        command,
        (
            RetryArtifactCommand,
            RegenerateArtifactCommand,
            TargetedUpdateArtifactCommand,
        ),
    ):
        return {"artifact_run_id": command.artifact_run_id}
    if isinstance(command, AnalyzeArtifactEvidenceCommand):
        return {"artifact_version_id": command.artifact_version_id}
    if isinstance(command, (CreateMediaRenderCommand,)):
        return {"artifact_version_id": command.artifact_version_id}
    if isinstance(command, (RetryFailedMediaTaskCommand, ReviewMediaRenderCommand)):
        return {"render_id": command.render_id}
    return {"artifact_version_id": command.artifact_version_id}


def command_requires_confirmation(_command: ApplicationCommand) -> bool:
    # Every command currently exposed to chat mutates durable state or starts provider work.
    return True


def dispatch_application_command(
    command: ApplicationCommand,
    *,
    session: Session,
    user: User,
    request_id: str | None,
    action_plan_id: int | None = None,
) -> object:
    if isinstance(command, CreateTransformationCommand):
        result = dispatch_manual_application_command(
            command,
            session=session,
            user=user,
            request_id=request_id,
        )
        target_type = "transformation"
        target_id = getattr(result, "transformation_run_id", None)
        if not isinstance(target_id, int):
            raise RuntimeError("Create command returned no transformation reference")
    elif isinstance(command, CreateTransformationAndGenerateCommand):
        from fastapi import HTTPException

        from app.api.generation import execute_generate_selected_artifacts
        from app.api.transformations import execute_create_transformation

        created = execute_create_transformation(
            command.request, user=user, session=session, request_id=request_id
        )
        try:
            batch = execute_generate_selected_artifacts(
                created.transformation_run_id, user, session
            )
            generation_status = batch.status
            artifact_runs = [
                CreatedArtifactRun(
                    artifact_run_id=item.artifact_run_id,
                    output_type=item.output_type,
                    status=item.status,
                )
                for item in batch.artifacts
            ]
            generation_error_code = None
            record_audit_event(
                session,
                owner_id=user.id,
                action_type="generation.requested",
                target_type="transformation",
                target_id=created.transformation_run_id,
                request_id=request_id,
                action_plan_id=action_plan_id,
            )
        except Exception as error:
            session.rollback()
            generation_status = "failed"
            artifact_runs = []
            detail = (
                cast(dict[str, object], error.detail)
                if isinstance(error, HTTPException) and isinstance(error.detail, dict)
                else {}
            )
            code = detail.get("code")
            generation_error_code = code if isinstance(code, str) else "generation_failed"
            record_audit_event(
                session,
                owner_id=user.id,
                action_type="generation.request_failed",
                target_type="transformation",
                target_id=created.transformation_run_id,
                request_id=request_id,
                action_plan_id=action_plan_id,
                outcome="failed",
                safe_metadata={"error_code": generation_error_code[:64]},
            )
        result = CreateTransformationAndGenerateResult(
            transformation_run_id=created.transformation_run_id,
            source_version_id=created.source_version.id,
            source_version_number=created.source_version.version_number,
            generation_status=generation_status,
            artifact_runs=artifact_runs,
            generation_error_code=generation_error_code,
        )
        target_type, target_id = "transformation", created.transformation_run_id
    elif isinstance(command, GenerateSelectedArtifactsCommand):
        from app.api.generation import execute_generate_selected_artifacts

        result = execute_generate_selected_artifacts(command.transformation_run_id, user, session)
        target_type, target_id = "transformation", command.transformation_run_id
    elif isinstance(command, RetryArtifactCommand):
        from app.api.generation import execute_retry_failed_artifact

        result = execute_retry_failed_artifact(command.artifact_run_id, user, session)
        target_type, target_id = "artifact_run", command.artifact_run_id
    elif isinstance(command, RegenerateArtifactCommand):
        from app.api.generation import execute_regenerate_artifact

        result = execute_regenerate_artifact(command.artifact_run_id, user, session)
        target_type, target_id = "artifact_run", command.artifact_run_id
    elif isinstance(command, TargetedUpdateArtifactCommand):
        from app.api.revisions import execute_targeted_update_artifact

        result = execute_targeted_update_artifact(command.artifact_run_id, user, session)
        target_type, target_id = "artifact_run", command.artifact_run_id
    elif isinstance(command, AnalyzeArtifactEvidenceCommand):
        raise TypeError("Evidence analysis requires async command dispatch")
    elif isinstance(command, CreateMediaRenderCommand):
        from app.api.media import CreateMediaRenderRequest, execute_start_media_render

        request = CreateMediaRenderRequest.model_validate(
            {
                "scene_durations_ms": command.scene_durations_ms,
                "scene_media": [item.model_dump(exclude_none=True) for item in command.scene_media],
            }
        )
        result = execute_start_media_render(command.artifact_version_id, request, user, session)
        target_type, target_id = "artifact_version", command.artifact_version_id
    elif isinstance(command, RetryFailedMediaTaskCommand):
        from app.api.media import execute_retry_failed_media_task

        result = execute_retry_failed_media_task(command.render_id, user, session)
        target_type, target_id = "media_render", command.render_id
    elif isinstance(command, ReviewMediaRenderCommand):
        from app.api.media import execute_review_media

        result = execute_review_media(
            command.render_id, command.decision, command.note, user, session
        )
        target_type, target_id = "media_render", command.render_id
    else:
        from app.api.reviews import execute_review_artifact_version

        result = execute_review_artifact_version(
            command.artifact_version_id, command.review_status, command.note, user, session
        )
        target_type, target_id = "artifact_version", command.artifact_version_id
    record_audit_event(
        session,
        owner_id=user.id,
        action_type=command.command_type,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        action_plan_id=action_plan_id,
    )
    session.commit()
    return result


async def dispatch_application_command_async(
    command: ApplicationCommand,
    *,
    session: Session,
    user: User,
    request_id: str | None,
    provider: StructuredGenerationProvider | None = None,
    expected_source_version_id: int | None = None,
    action_plan_id: int | None = None,
) -> object:
    if not isinstance(command, AnalyzeArtifactEvidenceCommand):
        return dispatch_application_command(
            command,
            session=session,
            user=user,
            request_id=request_id,
            action_plan_id=action_plan_id,
        )

    from app.api.evidence import execute_analyze_artifact_evidence

    result = await execute_analyze_artifact_evidence(
        command,
        user=user,
        session=session,
        provider=provider,
        expected_source_version_id=expected_source_version_id,
    )
    record_audit_event(
        session,
        owner_id=user.id,
        action_type=command.command_type,
        target_type="artifact_version",
        target_id=command.artifact_version_id,
        request_id=request_id,
        action_plan_id=action_plan_id,
    )
    session.commit()
    return result


def dispatch_manual_application_command(
    command: ManualApplicationCommand,
    *,
    session: Session,
    user: User,
    request_id: str | None,
) -> object:
    if isinstance(command, CreateTransformationCommand):
        from app.api.transformations import execute_create_transformation

        return execute_create_transformation(
            command.request, user=user, session=session, request_id=request_id
        )
    if isinstance(command, CreateSourceRevisionCommand):
        from app.api.revisions import execute_create_source_revision

        return execute_create_source_revision(
            command, user=user, session=session, request_id=request_id
        )
    if isinstance(command, ReviewEvidenceAssessmentCommand):
        from app.api.evidence import execute_review_claim_evidence

        return execute_review_claim_evidence(
            command, user=user, session=session, request_id=request_id
        )
    if isinstance(command, ReviewDiscrepancyFindingCommand):
        from app.api.evidence import execute_review_discrepancy_finding

        return execute_review_discrepancy_finding(
            command, user=user, session=session, request_id=request_id
        )
    if isinstance(command, UpdateMediaAssetRightsCommand):
        from app.api.media import execute_update_media_asset_rights

        return execute_update_media_asset_rights(
            command, user=user, session=session, request_id=request_id
        )
    if isinstance(command, UpdateSourceAssetRightsCommand):
        from app.api.sources import execute_update_source_asset_rights

        return execute_update_source_asset_rights(
            command, user=user, session=session, request_id=request_id
        )
    raise TypeError("Manual command requires async dispatch")


async def dispatch_manual_application_command_async(
    command: ManualApplicationCommand,
    *,
    session: Session,
    user: User,
    request_id: str | None,
    provider: StructuredGenerationProvider | None = None,
) -> object:
    if isinstance(command, SaveArtifactVersionCommand):
        from app.api.reviews import execute_save_artifact_version

        return await execute_save_artifact_version(
            command, user=user, session=session, provider=provider, request_id=request_id
        )
    if isinstance(command, VerifyArtifactEvidenceCommand):
        from app.api.evidence import execute_verify_artifact_evidence

        return await execute_verify_artifact_evidence(
            command, user=user, session=session, provider=provider, request_id=request_id
        )
    if isinstance(command, ResumeClaimScanCommand):
        from app.api.evidence import execute_resume_claim_scan

        return await execute_resume_claim_scan(
            command, user=user, session=session, provider=provider, request_id=request_id
        )
    if isinstance(command, AnalyzeSiblingConsistencyCommand):
        from app.api.evidence import execute_analyze_sibling_consistency

        return await execute_analyze_sibling_consistency(
            command, user=user, session=session, provider=provider, request_id=request_id
        )
    return dispatch_manual_application_command(
        command,
        session=session,
        user=user,
        request_id=request_id,
    )
