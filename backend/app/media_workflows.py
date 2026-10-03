"""Owner-scoped media render plans, bounded task execution, and provenance records."""

from __future__ import annotations

import tempfile
import time
from hashlib import sha256
from importlib.metadata import version as package_version
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.artifact_contracts import InfographicSpec
from app.job_queue import add_job_dependency, enqueue_media_job
from app.media_renderer import (
    INFOGRAPHIC_PROFILE,
    INFOGRAPHIC_RENDERER_VERSION,
    MAX_VIDEO_DURATION_MS,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_PROFILE,
    VIDEO_RENDERER_VERSION,
    VIDEO_WIDTH,
    MediaRenderError,
    canonical_hash,
    compose_mp4,
    deterministic_scene_duration_ms,
    infographic_spec_from_content,
    render_infographic,
    render_scene_card,
    video_spec_from_content,
    webvtt_for_plan,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Job,
    MediaAsset,
    MediaOperationMetric,
    MediaRender,
    MediaReviewDecision,
    MediaRightsRecord,
    MediaTask,
    TransformationRun,
    utc_now,
)
from app.private_asset_storage import (
    MAX_PRIVATE_ASSET_BYTES,
    MAX_RENDERED_MEDIA_BYTES,
    PrivateAssetStore,
    get_private_asset_store,
)

MEDIA_IMAGE_MAX_BYTES = 10 * 1024 * 1024
MEDIA_AUDIO_MAX_BYTES = 16 * 1024 * 1024
MEDIA_IMAGE_MAX_DIMENSION = 4_000
MEDIA_IMAGE_MAX_PIXELS = 16_000_000
MEDIA_AUDIO_MAX_DURATION_MS = 60_000


def media_owner_id(session: Session, version: ArtifactVersion) -> int | None:
    row = session.execute(
        select(TransformationRun.owner_id, ArtifactRun.output_type)
        .join(ArtifactRun, ArtifactRun.transformation_run_id == TransformationRun.id)
        .where(ArtifactRun.id == version.artifact_run_id)
    ).first()
    return row[0] if row else None


def media_family(session: Session, version: ArtifactVersion) -> str | None:
    return session.scalar(
        select(ArtifactRun.output_type).where(ArtifactRun.id == version.artifact_run_id)
    )


def rights_are_eligible(record: MediaRightsRecord | None) -> bool:
    if record is None or record.rights_basis == "unknown":
        return False
    if record.consent_required and record.consent_state != "confirmed":
        return False
    return record.consent_state in {"confirmed", "not_applicable"}


def _rights_for_asset(session: Session, asset: MediaAsset) -> MediaRightsRecord | None:
    return session.scalar(
        select(MediaRightsRecord).where(MediaRightsRecord.media_asset_id == asset.id)
    )


def _rights_snapshot(session: Session, asset: MediaAsset | None) -> dict[str, object] | None:
    record = _rights_for_asset(session, asset) if asset is not None else None
    if record is None:
        return None
    return {
        "rights_basis": record.rights_basis,
        "consent_state": record.consent_state,
        "consent_required": record.consent_required,
        "attribution": record.attribution,
        "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
    }


def _validate_optional_asset(
    session: Session, owner_id: int, asset_id: int, expected_purpose: str
) -> MediaAsset:
    asset = session.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.owner_id == owner_id)
    )
    if asset is None or asset.purpose != expected_purpose:
        raise ValueError("media_input_not_found")
    if not rights_are_eligible(_rights_for_asset(session, asset)):
        raise ValueError("media_input_rights_unresolved")
    return asset


def create_media_render(
    session: Session,
    owner_id: int,
    artifact_version: ArtifactVersion,
    *,
    scene_durations_ms: list[int | None] | None = None,
    scene_media: list[dict[str, int | None]] | None = None,
) -> MediaRender:
    family = media_family(session, artifact_version)
    if family not in {"infographic", "video_package"}:
        raise ValueError("media_render_unsupported_artifact")
    if media_owner_id(session, artifact_version) != owner_id:
        raise ValueError("artifact_version_not_found")

    if family == "infographic":
        spec = infographic_spec_from_content(artifact_version.content)
        profile = INFOGRAPHIC_PROFILE
        version = INFOGRAPHIC_RENDERER_VERSION
        plan: dict[str, object] = {
            "artifact_version_id": artifact_version.id,
            "family": family,
            "renderer_profile": profile,
            "renderer_version": version,
            "canvas_width": 1080,
            "minimum_canvas_height": 1350,
            "svg_and_png": True,
            "spec": spec.model_dump(mode="json"),
        }
    else:
        video = video_spec_from_content(artifact_version.content)
        if scene_durations_ms is not None and len(scene_durations_ms) != len(video.scenes):
            raise ValueError("scene_timing_count_mismatch")
        media_by_scene: dict[int, dict[str, int | None]] = {}
        for selection in scene_media or []:
            index = selection.get("scene_index")
            if not isinstance(index, int) or index < 0 or index >= len(video.scenes):
                raise ValueError("scene_media_index_invalid")
            if index in media_by_scene:
                raise ValueError("duplicate_scene_media_selection")
            media_by_scene[index] = selection
        plan_scenes: list[dict[str, object]] = []
        total_duration = 0
        for index, scene in enumerate(video.scenes):
            selection = media_by_scene.get(index, {})
            visual_id = selection.get("visual_asset_id")
            audio_id = selection.get("audio_asset_id")
            visual: MediaAsset | None = None
            audio: MediaAsset | None = None
            if visual_id is not None:
                visual = _validate_optional_asset(
                    session, owner_id, visual_id, "scene_visual_upload"
                )
            if audio_id is not None:
                audio = _validate_optional_asset(session, owner_id, audio_id, "scene_audio_upload")
            supplied_duration = (
                scene_durations_ms[index] if scene_durations_ms is not None else None
            )
            if supplied_duration is not None and (
                supplied_duration < 1_000 or supplied_duration > MAX_VIDEO_DURATION_MS
            ):
                raise ValueError("scene_duration_out_of_range")
            source_text = " ".join([scene.narration, *scene.on_screen_text]).strip()
            heuristic_duration = deterministic_scene_duration_ms(source_text)
            duration = supplied_duration or heuristic_duration
            timing_method = "user_selected" if supplied_duration is not None else "text_pacing_v1"
            if audio is not None and audio.duration_ms is not None and duration < audio.duration_ms:
                duration = audio.duration_ms
                timing_method = "expanded_to_approved_audio_duration"
            total_duration += duration
            plan_scenes.append(
                {
                    "scene_index": index,
                    "title": scene.title,
                    "narration": scene.narration,
                    "on_screen_text": scene.on_screen_text,
                    "visual_direction": scene.visual_direction,
                    "duration_ms": duration,
                    "timing_method": timing_method,
                    "transition_mode": "hard_cut",
                    "visual_asset_id": visual.id if visual else None,
                    "visual_asset_hash": visual.content_hash if visual else None,
                    "visual_rights": _rights_snapshot(session, visual),
                    "audio_asset_id": audio.id if audio else None,
                    "audio_asset_hash": audio.content_hash if audio else None,
                    "audio_duration_ms": audio.duration_ms if audio else None,
                    "audio_rights": _rights_snapshot(session, audio),
                }
            )
        if total_duration > MAX_VIDEO_DURATION_MS:
            raise ValueError("video_duration_limit_exceeded")
        audio_count = sum(1 for scene in plan_scenes if scene["audio_asset_id"] is not None)
        profile = VIDEO_PROFILE
        version = VIDEO_RENDERER_VERSION
        plan = {
            "artifact_version_id": artifact_version.id,
            "family": family,
            "renderer_profile": profile,
            "renderer_version": version,
            "width": VIDEO_WIDTH,
            "height": VIDEO_HEIGHT,
            "fps": VIDEO_FPS,
            "scenes": plan_scenes,
            "audio_coverage": "none"
            if audio_count == 0
            else "full"
            if audio_count == len(plan_scenes)
            else "partial",
            "audio_policy": "deterministic_silence_when_no_approved_scene_audio",
            "scene_timing_policy": "text_pacing_v1_expands_to_audio_duration",
            "caption_profile": "scene_narration_and_on_screen_text_v1",
        }

    dependency_key = canonical_hash(
        {
            "owner_id": owner_id,
            "artifact_version_id": artifact_version.id,
            "artifact_content_hash": sha256(artifact_version.content.encode()).hexdigest(),
            "plan": plan,
        }
    )
    render = MediaRender(
        owner_id=owner_id,
        artifact_version_id=artifact_version.id,
        artifact_family=family,
        renderer_profile=profile,
        renderer_version=version,
        render_plan=plan,
        render_plan_hash=canonical_hash(plan),
        dependency_key=dependency_key,
        status="pending",
    )
    session.add(render)
    session.flush()
    if family == "infographic":
        task = _create_task(session, render, owner_id, "render", "infographic_render", None, plan)
        enqueue_media_job(session, task, artifact_version.source_version_id)
    else:
        for scene in cast(list[dict[str, object]], plan["scenes"]):
            index = cast(int, scene["scene_index"])
            key = f"scene:{index}"
            dep_key = canonical_hash(
                {
                    "version": artifact_version.id,
                    "profile": version,
                    "scene": scene,
                }
            )
            task = MediaTask(
                owner_id=owner_id,
                render_id=render.id,
                task_key=key,
                task_kind="video_scene_render",
                dependency_key=dep_key,
                ordinal=index + 1,
                status="pending",
            )
            session.add(task)
            session.flush()
            _enqueue_or_reuse_scene(session, task, render, artifact_version, scene)
        _create_compose_if_ready(session, render, artifact_version)
    session.flush()
    return render


def _create_task(
    session: Session,
    render: MediaRender,
    owner_id: int,
    task_key: str,
    kind: str,
    ordinal: int | None,
    task_input: object,
) -> MediaTask:
    task = MediaTask(
        owner_id=owner_id,
        render_id=render.id,
        task_key=task_key,
        task_kind=kind,
        dependency_key=canonical_hash(
            {"render": render.dependency_key, "task": task_key, "input": task_input}
        ),
        ordinal=ordinal,
        status="pending",
    )
    session.add(task)
    session.flush()
    return task


def _enqueue_or_reuse_scene(
    session: Session,
    task: MediaTask,
    render: MediaRender,
    artifact_version: ArtifactVersion,
    scene: dict[str, object],
) -> None:
    previous_task = session.scalar(
        select(MediaTask)
        .where(
            MediaTask.owner_id == task.owner_id,
            MediaTask.task_kind == task.task_kind,
            MediaTask.dependency_key == task.dependency_key,
            MediaTask.status == "succeeded",
        )
        .order_by(MediaTask.id.desc())
    )
    previous_asset = (
        session.scalar(
            select(MediaAsset)
            .where(MediaAsset.task_id == previous_task.id)
            .order_by(MediaAsset.id.desc())
        )
        if previous_task is not None
        else None
    )
    store = get_private_asset_store()
    if previous_asset is not None:
        content = store.read(previous_asset.storage_key, max_bytes=MAX_RENDERED_MEDIA_BYTES)
        stored = store.store(content, max_bytes=MAX_RENDERED_MEDIA_BYTES)
        asset = MediaAsset(
            owner_id=task.owner_id,
            render_id=render.id,
            task_id=task.id,
            parent_media_asset_id=previous_asset.parent_media_asset_id,
            purpose="video_scene_frame",
            media_type=previous_asset.media_type,
            byte_size=stored.byte_size,
            content_hash=stored.content_hash,
            storage_key=stored.storage_key,
            width=previous_asset.width,
            height=previous_asset.height,
            renderer_profile=render.renderer_profile,
            renderer_version=render.renderer_version,
        )
        session.add(asset)
        task.status = "succeeded"
        task.completed_at = utc_now()
        session.add(
            Job(
                media_task_id=task.id,
                source_version_id=artifact_version.source_version_id,
                job_type="media_task",
                resource_class="media_cpu",
                status="succeeded",
                terminal_at=utc_now(),
            )
        )
        try:
            session.flush()
        except Exception:
            session.rollback()
            store.delete(stored.storage_key)
            raise
        _write_asset_rights(session, asset, previous_asset.parent_media_asset_id)
        return

    enqueue_media_job(session, task, artifact_version.source_version_id)


def _write_asset_rights(session: Session, asset: MediaAsset, parent_asset_id: int | None) -> None:
    if parent_asset_id is None:
        session.add(
            MediaRightsRecord(
                owner_id=asset.owner_id,
                media_asset_id=asset.id,
                rights_basis="system_generated",
                consent_state="not_applicable",
                consent_required=False,
            )
        )
        return
    parent = session.get(MediaAsset, parent_asset_id)
    rights = _rights_for_asset(session, parent) if parent is not None else None
    if rights is None:
        return
    session.add(
        MediaRightsRecord(
            owner_id=asset.owner_id,
            media_asset_id=asset.id,
            rights_basis=rights.rights_basis,
            consent_state=rights.consent_state,
            consent_required=rights.consent_required,
            attribution=rights.attribution,
            confirmed_by_user_id=rights.confirmed_by_user_id,
            confirmed_at=rights.confirmed_at,
        )
    )


def _write_composite_asset_rights(
    session: Session, asset: MediaAsset, inputs: list[MediaAsset]
) -> None:
    records = [_rights_for_asset(session, item) for item in inputs]
    if not inputs or all(
        record is not None and record.rights_basis == "system_generated" for record in records
    ):
        _write_asset_rights(session, asset, None)
        return
    if any(record is None for record in records):
        raise MediaRenderError("media_asset_rights_missing")
    typed_records = [record for record in records if record is not None]
    if any(record.consent_state == "unknown" for record in typed_records):
        consent_state = "unknown"
    elif any(record.consent_state == "confirmed" for record in typed_records):
        consent_state = "confirmed"
    else:
        consent_state = "not_applicable"
    session.add(
        MediaRightsRecord(
            owner_id=asset.owner_id,
            media_asset_id=asset.id,
            rights_basis="derived",
            consent_state=consent_state,
            consent_required=any(record.consent_required for record in typed_records),
        )
    )


def _create_compose_if_ready(
    session: Session, render: MediaRender, artifact_version: ArtifactVersion
) -> MediaTask | None:
    if render.artifact_family != "video_package":
        return None
    tasks = list(
        session.scalars(
            select(MediaTask).where(
                MediaTask.render_id == render.id,
                MediaTask.task_kind == "video_scene_render",
            )
        ).all()
    )
    if not tasks or any(task.status != "succeeded" for task in tasks):
        return None
    compose = session.scalar(
        select(MediaTask).where(
            MediaTask.render_id == render.id,
            MediaTask.task_kind == "video_compose",
        )
    )
    if compose is not None:
        return compose
    compose = _create_task(
        session,
        render,
        render.owner_id,
        "compose",
        "video_compose",
        None,
        render.render_plan_hash,
    )
    job = enqueue_media_job(session, compose, artifact_version.source_version_id)
    for task in tasks:
        scene_job = session.scalar(
            select(Job).where(Job.media_task_id == task.id, Job.status == "succeeded")
        )
        if scene_job is None:
            raise ValueError("successful_scene_job_missing")
        add_job_dependency(session, job.id, scene_job.id)
    render.status = "rendering"
    return compose


def _add_metric(
    session: Session,
    render: MediaRender,
    task: MediaTask,
    operation: str,
    elapsed_ms: int,
    input_bytes: int,
    output_bytes: int,
    tool_version: str,
    output_duration_ms: int | None = None,
) -> None:
    session.add(
        MediaOperationMetric(
            owner_id=render.owner_id,
            render_id=render.id,
            task_id=task.id,
            operation_type=operation,
            elapsed_ms=max(0, elapsed_ms),
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            output_duration_ms=output_duration_ms,
            tool_version=tool_version,
            external_api_cost=0,
        )
    )


def _store_derivative(
    session: Session,
    render: MediaRender,
    task: MediaTask,
    content: bytes,
    *,
    purpose: str,
    media_type: str,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
    parent_asset_id: int | None = None,
    write_default_rights: bool = True,
    storage: PrivateAssetStore | None = None,
) -> tuple[MediaAsset, str]:
    store = storage or get_private_asset_store()
    limit = (
        MAX_PRIVATE_ASSET_BYTES
        if len(content) <= MAX_PRIVATE_ASSET_BYTES
        else MAX_RENDERED_MEDIA_BYTES
    )
    stored = store.store(content, max_bytes=limit)
    asset = MediaAsset(
        owner_id=render.owner_id,
        render_id=render.id,
        task_id=task.id,
        parent_media_asset_id=parent_asset_id,
        purpose=purpose,
        media_type=media_type,
        byte_size=stored.byte_size,
        content_hash=stored.content_hash,
        storage_key=stored.storage_key,
        width=width,
        height=height,
        duration_ms=duration_ms,
        renderer_profile=render.renderer_profile,
        renderer_version=render.renderer_version,
    )
    session.add(asset)
    session.flush()
    if write_default_rights:
        _write_asset_rights(session, asset, parent_asset_id)
    return asset, stored.storage_key


def process_media_task(
    session_factory: sessionmaker[Session],
    claim: object,
    store: PrivateAssetStore | None = None,
) -> bool:
    """Run exactly one claimed bounded media task and persist its immutable outputs."""
    from app.job_queue import ClaimedJob

    if not isinstance(claim, ClaimedJob):
        raise TypeError("A claimed media job is required")
    with session_factory() as session:
        job = session.get(Job, claim.job_id)
        task = session.get(MediaTask, job.media_task_id) if job is not None else None
        render = session.get(MediaRender, task.render_id) if task is not None else None
        artifact = session.get(ArtifactVersion, render.artifact_version_id) if render else None
        if (
            job is None
            or task is None
            or render is None
            or artifact is None
            or job.resource_class != "media_cpu"
            or task.owner_id != render.owner_id
            or render.artifact_version_id != cast(int, render.render_plan["artifact_version_id"])
        ):
            _finish_failure(session_factory, claim, "media_task_inputs_missing")
            return True
        task_id = task.id
        render_id = render.id
        plan = render.render_plan
        content = artifact.content
        task_kind = task.task_kind

    if task_kind == "infographic_render":
        return _run_infographic(session_factory, claim, task_id, render_id, plan, content, store)
    if task_kind == "video_scene_render":
        return _run_video_scene(session_factory, claim, task_id, render_id, plan, content, store)
    if task_kind == "video_compose":
        return _run_video_compose(session_factory, claim, task_id, render_id, plan, content, store)
    _finish_failure(session_factory, claim, "unsupported_media_task")
    return True


def _run_infographic(
    session_factory: sessionmaker[Session],
    claim: object,
    task_id: int,
    render_id: int,
    plan: dict[str, object],
    content: str,
    store: PrivateAssetStore | None,
) -> bool:
    from app.job_queue import ClaimedJob

    assert isinstance(claim, ClaimedJob)
    started = time.perf_counter()
    keys: list[str] = []
    asset_store = store or get_private_asset_store()
    try:
        spec = InfographicSpec.model_validate(plan["spec"])
        svg, png, width, height = render_infographic(spec)
        with session_factory() as session:
            task, render, artifact, job, attempt = _claimed_rows(session, claim, task_id, render_id)
            if artifact.content != content or artifact.id != render.artifact_version_id:
                raise MediaRenderError("artifact_version_mismatch")
            _svg_asset, svg_key = _store_derivative(
                session,
                render,
                task,
                svg,
                purpose="infographic_svg",
                media_type="image/svg+xml",
                width=width,
                height=height,
                storage=asset_store,
            )
            keys.append(svg_key)
            png_asset, png_key = _store_derivative(
                session,
                render,
                task,
                png,
                purpose="infographic_png",
                media_type="image/png",
                width=width,
                height=height,
                storage=asset_store,
            )
            keys.append(png_key)
            render.primary_asset_id = png_asset.id
            render.status = "ready_for_review"
            render.completed_at = utc_now()
            _add_metric(
                session,
                render,
                task,
                "infographic_render",
                round((time.perf_counter() - started) * 1000),
                len(content.encode()),
                len(svg) + len(png),
                f"{render.renderer_profile}/{render.renderer_version};PyMuPDF={fitz_version()}",
            )
            _finish_success_rows(task, render, job, attempt)
            session.flush()
            session.commit()
            return True
    except MediaRenderError as error:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, error.code)
        return True
    except Exception:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, "media_render_failed")
        return True


def _run_video_scene(
    session_factory: sessionmaker[Session],
    claim: object,
    task_id: int,
    render_id: int,
    plan: dict[str, object],
    content: str,
    store: PrivateAssetStore | None,
) -> bool:
    from app.job_queue import ClaimedJob

    assert isinstance(claim, ClaimedJob)
    started = time.perf_counter()
    keys: list[str] = []
    asset_store = store or get_private_asset_store()
    try:
        with session_factory() as session:
            task, render, artifact, _job, _attempt = _claimed_rows(
                session, claim, task_id, render_id
            )
            if artifact.content != content or artifact.id != render.artifact_version_id:
                raise MediaRenderError("artifact_version_mismatch")
            scenes = cast(list[dict[str, object]], plan["scenes"])
            scene = next(
                item for item in scenes if cast(int, item["scene_index"]) == (task.ordinal or 1) - 1
            )
            visual_id = cast(int | None, scene.get("visual_asset_id"))
            visual_content = None
            parent_asset_id = visual_id
            if visual_id is not None:
                visual = _validate_optional_asset(
                    session, task.owner_id, visual_id, "scene_visual_upload"
                )
                visual_content = asset_store.read(
                    visual.storage_key, max_bytes=MEDIA_IMAGE_MAX_BYTES
                )
            task_input_bytes = len(content.encode()) + (
                len(visual_content) if visual_content else 0
            )
            scene_title = cast(str, scene["title"])
            onscreen = cast(list[str], scene["on_screen_text"])
        png, width, height = render_scene_card(
            scene_title,
            onscreen,
            visual_bytes=visual_content,
        )
        with session_factory() as session:
            task, render, _artifact, job, attempt = _claimed_rows(
                session, claim, task_id, render_id
            )
            _asset, key = _store_derivative(
                session,
                render,
                task,
                png,
                purpose="video_scene_frame",
                media_type="image/png",
                width=width,
                height=height,
                parent_asset_id=parent_asset_id,
                storage=asset_store,
            )
            keys.append(key)
            elapsed = round((time.perf_counter() - started) * 1000)
            _add_metric(
                session,
                render,
                task,
                "video_scene_render",
                elapsed,
                task_input_bytes,
                len(png),
                f"{render.renderer_profile}/{render.renderer_version};PyMuPDF={fitz_version()}",
            )
            _finish_success_rows(task, render, job, attempt)
            artifact_version = session.get(ArtifactVersion, render.artifact_version_id)
            if artifact_version is None:
                raise MediaRenderError("artifact_version_missing")
            _create_compose_if_ready(session, render, artifact_version)
            session.commit()
            return True
    except MediaRenderError as error:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, error.code)
        return True
    except Exception:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, "scene_render_failed")
        return True


def _run_video_compose(
    session_factory: sessionmaker[Session],
    claim: object,
    task_id: int,
    render_id: int,
    plan: dict[str, object],
    content: str,
    store: PrivateAssetStore | None,
) -> bool:
    from app.job_queue import ClaimedJob

    assert isinstance(claim, ClaimedJob)

    asset_store = store or get_private_asset_store()
    started = time.perf_counter()
    keys: list[str] = []
    try:
        with session_factory() as session:
            task, render, artifact, _job, _attempt = _claimed_rows(
                session, claim, task_id, render_id
            )
            if artifact.content != content or artifact.id != render.artifact_version_id:
                raise MediaRenderError("artifact_version_mismatch")
            scenes = cast(list[dict[str, object]], plan["scenes"])
            scene_rows = list(
                session.scalars(
                    select(MediaTask)
                    .where(
                        MediaTask.render_id == render.id,
                        MediaTask.task_kind == "video_scene_render",
                    )
                    .order_by(MediaTask.ordinal)
                ).all()
            )
            if len(scene_rows) != len(scenes) or any(
                row.status != "succeeded" for row in scene_rows
            ):
                raise MediaRenderError("scene_outputs_not_committed")
            scene_assets: list[MediaAsset] = []
            audio_assets: list[MediaAsset | None] = []
            for scene_task, scene in zip(scene_rows, scenes, strict=True):
                scene_asset = session.scalar(
                    select(MediaAsset).where(
                        MediaAsset.task_id == scene_task.id,
                        MediaAsset.purpose == "video_scene_frame",
                        MediaAsset.owner_id == render.owner_id,
                    )
                )
                if scene_asset is None:
                    raise MediaRenderError("scene_output_missing")
                scene_assets.append(scene_asset)
                audio_id = cast(int | None, scene.get("audio_asset_id"))
                if audio_id is None:
                    audio_assets.append(None)
                else:
                    audio_asset = _validate_optional_asset(
                        session, render.owner_id, audio_id, "scene_audio_upload"
                    )
                    audio_assets.append(audio_asset)
            duration_ms = [cast(int, scene["duration_ms"]) for scene in scenes]
            input_bytes = sum(asset.byte_size for asset in scene_assets)
            input_bytes += sum(asset.byte_size for asset in audio_assets if asset is not None)
        with tempfile.TemporaryDirectory(prefix="axiomweave-compose-") as folder:
            workdir = Path(folder)
            scene_paths: list[Path] = []
            audio_paths: list[Path | None] = []
            for index, (scene_asset, audio_asset) in enumerate(
                zip(scene_assets, audio_assets, strict=True)
            ):
                image_path = workdir / f"scene_{index:03d}.png"
                image_path.write_bytes(
                    asset_store.read(scene_asset.storage_key, max_bytes=MEDIA_IMAGE_MAX_BYTES)
                )
                scene_paths.append(image_path)
                if audio_asset is None:
                    audio_paths.append(None)
                else:
                    audio_path = workdir / f"audio_{index:03d}.bin"
                    audio_path.write_bytes(
                        asset_store.read(audio_asset.storage_key, max_bytes=MEDIA_AUDIO_MAX_BYTES)
                    )
                    audio_paths.append(audio_path)
            mp4_path = workdir / "final.mp4"
            probe, scene_count = compose_mp4(
                mp4_path, scene_paths, audio_paths, duration_ms, workdir
            )
            mp4_bytes = mp4_path.read_bytes()
        vtt = webvtt_for_plan(plan)
        with session_factory() as session:
            task, render, _artifact, job, attempt = _claimed_rows(
                session, claim, task_id, render_id
            )
            # Verify that all attached rights states are still resolved immediately before commit.
            for scene in cast(list[dict[str, object]], plan["scenes"]):
                for key in ("visual_asset_id", "audio_asset_id"):
                    asset_id = cast(int | None, scene.get(key))
                    if asset_id is not None:
                        purpose = (
                            "scene_visual_upload"
                            if key == "visual_asset_id"
                            else "scene_audio_upload"
                        )
                        _validate_optional_asset(session, render.owner_id, asset_id, purpose)
            video_asset, video_key = _store_derivative(
                session,
                render,
                task,
                mp4_bytes,
                purpose="final_mp4",
                media_type="video/mp4",
                width=probe.width,
                height=probe.height,
                duration_ms=probe.duration_ms,
                write_default_rights=False,
                storage=asset_store,
            )
            composite_inputs = [
                *scene_assets,
                *(asset for asset in audio_assets if asset is not None),
            ]
            _write_composite_asset_rights(session, video_asset, composite_inputs)
            keys.append(video_key)
            _vtt_asset, vtt_key = _store_derivative(
                session,
                render,
                task,
                vtt,
                purpose="caption_vtt",
                media_type="text/vtt",
                duration_ms=probe.duration_ms,
                storage=asset_store,
            )
            keys.append(vtt_key)
            render.primary_asset_id = video_asset.id
            render.status = "ready_for_review"
            render.completed_at = utc_now()
            elapsed = round((time.perf_counter() - started) * 1000)
            _add_metric(
                session,
                render,
                task,
                "video_compose",
                elapsed,
                input_bytes,
                len(mp4_bytes) + len(vtt),
                f"{render.renderer_profile}/{render.renderer_version};{probe.tool_version}",
                probe.duration_ms,
            )
            session.add(
                MediaOperationMetric(
                    owner_id=render.owner_id,
                    render_id=render.id,
                    task_id=task.id,
                    operation_type="video_scene_total",
                    elapsed_ms=elapsed,
                    input_bytes=input_bytes,
                    output_bytes=sum(asset.byte_size for asset in scene_assets),
                    tool_version=f"{render.renderer_profile}/{render.renderer_version};scenes={scene_count}",
                    external_api_cost=0,
                )
            )
            _finish_success_rows(task, render, job, attempt)
            session.commit()
            return True
    except MediaRenderError as error:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, error.code)
        return True
    except Exception:
        _cleanup_keys(asset_store, keys)
        _finish_failure(session_factory, claim, "video_compose_failed")
        return True


def _claimed_rows(
    session: Session, claim: object, task_id: int, render_id: int
) -> tuple[MediaTask, MediaRender, ArtifactVersion, Job, object]:
    from app.job_queue import ClaimedJob
    from app.models import JobAttempt

    if not isinstance(claim, ClaimedJob):
        raise TypeError("A claimed media job is required")
    job = session.scalar(select(Job).where(Job.id == claim.job_id).with_for_update())
    task = session.get(MediaTask, task_id)
    render = session.get(MediaRender, render_id)
    artifact = session.get(ArtifactVersion, render.artifact_version_id) if render else None
    attempt = session.scalar(
        select(JobAttempt).where(
            JobAttempt.job_id == claim.job_id,
            JobAttempt.attempt_number == claim.attempt_number,
            JobAttempt.status == "running",
        )
    )
    if (
        job is None
        or task is None
        or render is None
        or artifact is None
        or attempt is None
        or job.status != "running"
        or job.worker_id != claim.worker_id
    ):
        raise MediaRenderError("media_task_lease_lost")
    return task, render, artifact, job, attempt


def _finish_success_rows(task: MediaTask, render: MediaRender, job: Job, attempt: object) -> None:
    from app.models import JobAttempt

    if not isinstance(attempt, JobAttempt):
        raise TypeError("A running job attempt is required")
    now = utc_now()
    task.status = "succeeded"
    task.failure_code = None
    task.completed_at = now
    job.status = "succeeded"
    job.failure_code = None
    job.worker_id = None
    job.lease_expires_at = None
    job.terminal_at = now
    attempt.status = "succeeded"
    attempt.failure_code = None
    attempt.finished_at = now


def _finish_failure(
    session_factory: sessionmaker[Session], claim: object, failure_code: str
) -> None:
    from app.job_queue import ClaimedJob
    from app.models import JobAttempt

    if not isinstance(claim, ClaimedJob):
        return
    with session_factory() as session:
        job = session.scalar(select(Job).where(Job.id == claim.job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != claim.worker_id:
            session.rollback()
            return
        task = session.get(MediaTask, job.media_task_id)
        attempt = session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == claim.job_id,
                JobAttempt.attempt_number == claim.attempt_number,
                JobAttempt.status == "running",
            )
        )
        now = utc_now()
        if task is not None:
            task.status = "failed"
            task.failure_code = failure_code
            task.completed_at = now
        job.status = "failed"
        job.failure_code = failure_code
        job.worker_id = None
        job.lease_expires_at = None
        job.terminal_at = now
        if isinstance(attempt, JobAttempt):
            attempt.status = "failed"
            attempt.failure_code = failure_code
            attempt.finished_at = now
        render = session.get(MediaRender, task.render_id) if task is not None else None
        if render is not None:
            if task is not None and task.task_kind == "video_scene_render":
                render.status = "partial_failure"
            else:
                render.status = "failed"
                render.failure_code = failure_code
                render.completed_at = now
        session.commit()


def _cleanup_keys(store: PrivateAssetStore, keys: list[str]) -> None:
    for key in keys:
        try:
            store.delete(key)
        except OSError:
            pass


def fitz_version() -> str:
    return package_version("PyMuPDF")


def review_media_render(
    session: Session,
    render: MediaRender,
    owner_id: int,
    decision: str,
    note: str | None,
) -> MediaReviewDecision:
    asset = session.get(MediaAsset, render.primary_asset_id) if render.primary_asset_id else None
    if asset is None or asset.render_id != render.id or asset.owner_id != owner_id:
        raise ValueError("media_primary_asset_missing")
    if render.status not in {"ready_for_review", "approved", "rejected"}:
        raise ValueError("media_render_not_reviewable")
    record = MediaReviewDecision(
        owner_id=owner_id,
        media_render_id=render.id,
        primary_asset_hash=asset.content_hash,
        decision=decision,
        note=note.strip() if note else None,
        created_at=utc_now(),
    )
    session.add(record)
    render.status = decision
    session.flush()
    return record


def format_caption_for_human(plan: dict[str, object]) -> str:
    return webvtt_for_plan(plan).decode("utf-8")
