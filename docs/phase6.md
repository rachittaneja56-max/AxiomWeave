# Phase 6 implementation status

Phase 6 adds bounded ActionPlan chat, shared typed handlers for the current chat command set, request security, task-based model policy, audit/usage records, rate limits, readiness reporting, SQLite recovery tooling, and final-release evaluation materials.

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

Other existing mutations such as source revision, manual artifact edits, evidence adjudication, consistency dismissal, and media/source rights updates remain on their existing owner-scoped APIs and are not currently exposed as chat commands. Chat covers the listed command set; extending it to those operations would require additional product decisions about which content may be proposed conversationally. No ActionPlan can invoke arbitrary tools or select a model/provider.

## Evaluation and human gates

The held-out fixture and candidate registry are in `backend/evals/release/`. Run `uv run python -m scripts.release_harness --output-root .\release-runs --task action_planning --candidate-label A` from `backend` to prepare a fresh blinded evaluation folder. It does not run model comparisons. The model registry, final acceptance worksheet, and claim register are under `docs/judge/`.

Final model selection, real-model held-out evaluation, Phase-5 media quality review, manual owner demo acceptance, and production release remain pending. This implementation does not authorize a production migration or deployment.
