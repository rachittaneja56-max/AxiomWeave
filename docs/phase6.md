# Phase 6 implementation status

Phase 6 adds bounded ActionPlan chat, a shared typed command layer for chat and important manual mutations, request security, task-based model policy, audit/usage records, rate limits, readiness reporting, SQLite recovery tooling, and final-release evaluation materials.

## Current manual/chat command parity

| Operation | Manual API entry point | Shared handler | Chat command | Automated parity evidence |
|---|---|---|---|---|
| Generate selected artifact families | `POST /api/transformations/{id}/generate` | `GenerateSelectedArtifactsCommand` | `generate_selected_artifacts` | owner isolation and confirmed execution tests |
| Retry failed artifact | `POST /api/artifact-runs/{id}/retry` | `RetryArtifactCommand` | `retry_artifact` | cross-owner manual/chat denial test |
| Regenerate artifact | `POST /api/artifact-runs/{id}/regenerate` | `RegenerateArtifactCommand` | `regenerate_artifact` | command validation/state checks |
| Targeted artifact update | `POST /api/artifact-runs/{id}/targeted-update` | `TargetedUpdateArtifactCommand` | `targeted_update_artifact` | cross-owner manual/chat denial and exact-state revalidation |
| Analyze artifact evidence | `POST /api/artifact-versions/{id}/evidence/analyze` | `AnalyzeArtifactEvidenceCommand` | `analyze_artifact_evidence` | exact artifact/source validation and equivalent manual/chat audit events |
| Accept/reject artifact version | `PATCH /api/artifact-versions/{id}/review` | `ReviewArtifactVersionCommand` | `review_artifact_version` | owned-version validation in handler |
| Create media render | `POST /api/artifact-versions/{id}/media-renders` | `CreateMediaRenderCommand` | `create_media_render` | cross-owner manual/chat denial; rights are rechecked at confirmation |
| Retry failed media task | `POST /api/media-renders/{id}/retry-failed` | `RetryFailedMediaTaskCommand` | `retry_failed_media_task` | owner and failed-task state checked at proposal and execution |
| Review media render | `PATCH /api/media-renders/{id}/review` | `ReviewMediaRenderCommand` | `review_media_render` | exact owner/render asset and current state checked |

These additional owner-scoped manual mutations also enter typed handlers, but are not offered as chat commands:

| Manual operation | API entry point | Typed handler |
|---|---|---|
| Create transformation | `POST /api/transformations` | `CreateTransformationCommand` |
| Create source revision | `POST /api/transformations/{id}/source-versions` | `CreateSourceRevisionCommand` |
| Save edited artifact version | `POST /api/artifact-runs/{id}/versions` | `SaveArtifactVersionCommand` |
| Review evidence assessment | `PATCH /api/claim-evidence-assessments/{id}/review` | `ReviewEvidenceAssessmentCommand` |
| Verify evidence / resume claim scan | `POST /api/artifact-versions/{id}/evidence/verify`, `POST /api/claim-scans/{id}/resume` | `VerifyArtifactEvidenceCommand`, `ResumeClaimScanCommand` |
| Analyze consistency | `POST /api/discrepancies/analyze` | `AnalyzeSiblingConsistencyCommand` |
| Dismiss discrepancy | `PATCH /api/discrepancies/{id}` | `ReviewDiscrepancyFindingCommand` |
| Update source or rendered media rights | `PATCH /api/source-assets/{id}/rights`, `PATCH /api/media-assets/{id}/rights` | `UpdateSourceAssetRightsCommand`, `UpdateMediaAssetRightsCommand` |

No ActionPlan can invoke arbitrary tools or select a model/provider.

## Evaluation and human gates

The held-out fixture and candidate registry are in `backend/evals/release/`. Run `uv run python -m scripts.release_harness --output-root .\release-runs --task action_planning --candidate-label A` from `backend` to prepare a fresh blinded evaluation folder. It does not run model comparisons. The model registry, final acceptance worksheet, and claim register are under `docs/judge/`.

Final model selection, real-model held-out evaluation, Phase-5 media quality review, manual owner demo acceptance, and production release remain pending. This implementation does not authorize a production migration or deployment.
