import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import fitz as _fitz  # pyright: ignore[reportMissingTypeStubs]
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.artifact_contracts import InfographicSpec, VideoPackageSpec
from app.job_queue import MEDIA_CPU, claim_next_job
from app.media_renderer import (
    ProbeResult,
    compose_mp4,
    infographic_svg,
    render_scene_card,
    webvtt_for_plan,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Job,
    JobAttempt,
    JobDependency,
    MediaAsset,
    MediaRender,
    MediaReviewDecision,
    MediaRightsRecord,
    MediaTask,
    SourceVersion,
    TransformationRun,
    User,
    utc_now,
)
from app.private_asset_storage import (
    MAX_PRIVATE_ASSET_BYTES,
    AssetStorageError,
    LocalPrivateAssetStore,
    StoredPrivateAsset,
)
from app.source_versions import create_source_pack_version

fitz: Any = _fitz

INFOGRAPHIC = InfographicSpec.model_validate(
    {
        "title": "Community update",
        "subtitle": "A deterministic fixture",
        "key_message": "Dates stay exact",
        "blocks": [
            {"type": "section", "heading": "Schedule", "body": "Doors open Friday."},
            {
                "type": "callout",
                "label": "Time",
                "value": "09:30",
                "explanation": "The source value remains unchanged.",
            },
            {
                "type": "data",
                "heading": "Details",
                "rows": [{"label": "Location", "value": "Hall A", "note": "Main entrance"}],
            },
        ],
        "visual_direction": "Calm green and cream layout",
    }
)

VIDEO = VideoPackageSpec.model_validate(
    {
        "title": "Community update",
        "concept": "A short fixture video.",
        "scenes": [
            {
                "title": "Scene A",
                "narration": "The doors open Friday.",
                "on_screen_text": ["Friday"],
                "visual_direction": "Clean title card",
                "transition_notes": "Hard cut",
            },
            {
                "title": "Scene B",
                "narration": "The program begins at half past nine.",
                "on_screen_text": ["09:30"],
                "visual_direction": "Clean title card",
                "transition_notes": "Hard cut",
            },
            {
                "title": "Scene C",
                "narration": "Visitors enter through Hall A.",
                "on_screen_text": ["Hall A"],
                "visual_direction": "Clean title card",
                "transition_notes": "End card",
            },
        ],
    }
)


def _create_version(
    factory: sessionmaker[Session], username: str, output_type: str, content: str
) -> tuple[int, int]:
    with factory() as session:
        owner = session.scalar(select(User).where(User.username == username.replace("-", "_")))
        assert owner is not None
        source_write = create_source_pack_version(session, owner.id, "The doors open Friday.")
        source_version: SourceVersion = source_write.source_version
        transformation = TransformationRun(
            owner_id=owner.id,
            source_version_id=source_version.id,
            audience="Community",
            tone="Clear",
            language="English",
            detail_level="standard",
            objective="Inform",
            style="Plain language",
            selected_output_types=[output_type],
        )
        session.add(transformation)
        session.flush()
        run = ArtifactRun(
            transformation_run_id=transformation.id,
            output_type=output_type,
            status="succeeded",
        )
        session.add(run)
        session.flush()
        version = ArtifactVersion(
            artifact_run_id=run.id,
            version_number=1,
            source_version_id=source_version.id,
            content=content,
            review_status="draft",
        )
        session.add(version)
        session.commit()
        return version.id, owner.id


def test_infographic_svg_is_deterministic_and_escapes_untrusted_text() -> None:
    unsafe = INFOGRAPHIC.model_copy(update={"title": '<script onload="x">& update'})

    first, width, height = infographic_svg(unsafe)
    second, _, _ = infographic_svg(unsafe)
    markup = first.decode()

    assert first == second
    assert width == 1080 and height >= 1350
    assert "&lt;script onload=&quot;x&quot;&gt;&amp; update" in markup
    assert "<script" not in markup
    assert "foreignObject" not in markup
    assert "http://" not in markup.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "09:30" in markup


def test_scene_visuals_and_caption_timing_are_deterministic() -> None:
    first, width, height = render_scene_card("Scene title", ["Approved display text"])
    second, _, _ = render_scene_card("Scene title", ["Approved display text"])
    plan: dict[str, Any] = {
        "scenes": [
            {
                "title": "Scene title",
                "narration": "Approved narration.",
                "on_screen_text": ["Approved display text"],
                "duration_ms": 4_000,
            },
            {
                "title": "End",
                "narration": "",
                "on_screen_text": ["Finished"],
                "duration_ms": 3_000,
            },
        ]
    }
    captions = webvtt_for_plan(plan).decode()

    assert first == second
    assert (width, height) == (1280, 720)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert "00:00:00.000 --> 00:00:04.000" in captions
    assert "00:00:04.000 --> 00:00:07.000" in captions
    assert "Approved narration." in captions


def test_private_asset_store_requires_explicit_media_limit(tmp_path: Path) -> None:
    store = LocalPrivateAssetStore(tmp_path / "private")
    content = b"x" * (MAX_PRIVATE_ASSET_BYTES + 1)

    with pytest.raises(AssetStorageError):
        store.store(content)
    stored = store.store(content, max_bytes=len(content))

    assert store.read(stored.storage_key, max_bytes=len(content)) == content


def test_infographic_render_targets_exact_artifact_version_and_review_is_historical(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    version_id, owner_id = _create_version(
        factory, "subject-1", "infographic", INFOGRAPHIC.model_dump_json()
    )
    started = authorized_client.post(f"/api/artifact-versions/{version_id}/media-renders", json={})

    assert started.status_code == 202
    render = started.json()
    assert render["artifact_version_id"] == version_id
    assert render["render_plan"]["artifact_version_id"] == version_id
    assert render["tasks"][0]["task_kind"] == "infographic_render"
    assert render["tasks"][0]["job_status"] == "queued"

    with factory() as session:
        version_one = session.get(ArtifactVersion, version_id)
        assert version_one is not None
        version_two = ArtifactVersion(
            artifact_run_id=version_one.artifact_run_id,
            version_number=2,
            source_version_id=version_one.source_version_id,
            content=INFOGRAPHIC.model_copy(update={"title": "Version two"}).model_dump_json(),
            review_status="draft",
        )
        session.add(version_two)
        session.commit()
        version_two_id = version_two.id
    second_render = authorized_client.post(
        f"/api/artifact-versions/{version_two_id}/media-renders", json={}
    )
    assert second_render.status_code == 202
    assert second_render.json()["render_plan"]["spec"]["title"] == "Version two"

    from app.media_worker import process_one_media_job

    assert process_one_media_job(factory, "infographic-test-worker")
    rendered = authorized_client.get(f"/api/media-renders/{render['id']}").json()
    assert rendered["status"] == "ready_for_review"
    assert rendered["primary_asset"]["purpose"] == "infographic_png"
    assert rendered["primary_asset"]["preview_url"].startswith("/api/media-assets/")
    assert "storage_key" not in rendered["primary_asset"]
    purposes = {item["purpose"] for task in rendered["tasks"] for item in task["assets"]}
    assert {"infographic_svg", "infographic_png"} <= purposes
    assert process_one_media_job(factory, "infographic-test-worker")
    rendered_version_two = authorized_client.get(
        f"/api/media-renders/{second_render.json()['id']}"
    ).json()
    assert rendered_version_two["status"] == "ready_for_review"
    assert rendered_version_two["render_plan"]["spec"]["title"] == "Version two"

    first_review = authorized_client.patch(
        f"/api/media-renders/{render['id']}/review", json={"decision": "approved"}
    )
    second_review = authorized_client.patch(
        f"/api/media-renders/{render['id']}/review",
        json={"decision": "rejected", "note": "Fixture review history test."},
    )
    assert first_review.status_code == second_review.status_code == 200
    history = second_review.json()["reviews"]
    assert [item["decision"] for item in history] == ["approved", "rejected"]
    assert history[0]["primary_asset_hash"] == rendered["primary_asset"]["content_hash"]
    assert history[1]["reviewer_user_id"] == owner_id
    assert "does not certify factual claims" in second_review.json()["review_copy"]
    with factory() as session:
        assert (
            session.scalar(
                select(MediaReviewDecision).where(
                    MediaReviewDecision.media_render_id == render["id"]
                )
            )
            is not None
        )
    from auth_support import login

    login(authorized_client, "media-workflow-other-owner")
    assert authorized_client.get(rendered["primary_asset"]["preview_url"]).status_code == 404
    assert authorized_client.get(f"/api/media-renders/{render['id']}").status_code == 404


def test_video_scene_failure_retry_preserves_success_and_reuses_identical_frames(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, _engine, factory = auth_database
    version_id, _owner_id = _create_version(
        factory, "subject-1", "video_package", VIDEO.model_dump_json()
    )
    calls: list[str] = []
    fail_once = True

    def render_card(
        title: str, lines: list[str], *, visual_bytes: bytes | None = None
    ) -> tuple[bytes, int, int]:
        nonlocal fail_once
        calls.append(title)
        if title == "Scene B" and fail_once:
            fail_once = False
            from app.media_renderer import MediaRenderError

            raise MediaRenderError("fixture_scene_failure")
        return b"frame:" + title.encode(), 1280, 720

    def compose(
        output_path: Path,
        scene_paths: list[Path],
        audio_paths: list[Path | None],
        durations_ms: list[int],
        workdir: Path,
    ) -> tuple[ProbeResult, int]:
        output_path.write_bytes(b"fixture-mp4-content")
        return ProbeResult(
            1280, 720, sum(durations_ms), 30.0, True, True, "fixture-ffmpeg/ffprobe", "mp4"
        ), len(scene_paths)

    monkeypatch.setattr("app.media_workflows.render_scene_card", render_card)
    monkeypatch.setattr("app.media_workflows.compose_mp4", compose)
    started = authorized_client.post(f"/api/artifact-versions/{version_id}/media-renders", json={})
    assert started.status_code == 202
    render_id = started.json()["id"]

    from app.media_worker import process_one_media_job

    assert process_one_media_job(factory, "video-test-worker")
    assert process_one_media_job(factory, "video-test-worker")
    assert process_one_media_job(factory, "video-test-worker")
    partial = authorized_client.get(f"/api/media-renders/{render_id}").json()
    assert partial["status"] == "partial_failure"
    assert {task["status"] for task in partial["tasks"]} == {"failed", "succeeded"}
    assert sum(len(task["assets"]) for task in partial["tasks"]) == 2
    assert all(task["task_kind"] != "video_compose" for task in partial["tasks"])

    retried = authorized_client.post(f"/api/media-renders/{render_id}/retry-failed")
    assert retried.status_code == 202
    assert process_one_media_job(factory, "video-test-worker")
    assert process_one_media_job(factory, "video-test-worker")
    ready = authorized_client.get(f"/api/media-renders/{render_id}").json()
    assert ready["status"] == "ready_for_review"
    assert ready["primary_asset"]["purpose"] == "final_mp4"
    assert any(
        asset["purpose"] == "caption_vtt" for task in ready["tasks"] for asset in task["assets"]
    )
    assert calls == ["Scene A", "Scene B", "Scene C", "Scene B"]
    with factory() as session:
        scene_tasks = list(
            session.scalars(
                select(MediaTask).where(
                    MediaTask.render_id == render_id,
                    MediaTask.task_kind == "video_scene_render",
                )
            )
        )
        assert len(scene_tasks) == 3
        compose_task = session.scalar(
            select(MediaTask).where(
                MediaTask.render_id == render_id,
                MediaTask.task_kind == "video_compose",
            )
        )
        assert compose_task is not None
        compose_job = session.scalar(select(Job).where(Job.media_task_id == compose_task.id))
        assert compose_job is not None
        dependencies = list(
            session.scalars(select(JobDependency).where(JobDependency.job_id == compose_job.id))
        )
        assert len(dependencies) == 3
        assert (
            session.scalar(
                select(MediaAsset).where(
                    MediaAsset.render_id == render_id,
                    MediaAsset.purpose == "video_scene_frame",
                )
            )
            is not None
        )

    # The exact same scene inputs reuse successful content-addressed frames in a new render.
    duplicate = authorized_client.post(
        f"/api/artifact-versions/{version_id}/media-renders", json={}
    )
    assert duplicate.status_code == 202
    reused = duplicate.json()
    assert all(
        task["status"] == "succeeded"
        for task in reused["tasks"]
        if task["task_kind"] == "video_scene_render"
    )
    assert calls == ["Scene A", "Scene B", "Scene C", "Scene B"]
    assert process_one_media_job(factory, "video-test-worker")
    reused_ready = authorized_client.get(f"/api/media-renders/{reused['id']}").json()
    assert reused_ready["status"] == "ready_for_review"


def test_media_render_refuses_unresolved_external_asset_rights(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, _engine, factory = auth_database
    version_id, _owner_id = _create_version(
        factory, "subject-1", "video_package", VIDEO.model_dump_json()
    )
    document = fitz.open()
    document.new_page(width=80, height=60).draw_rect(fitz.Rect(5, 5, 40, 30), fill=(1, 0, 0))
    image_bytes: bytes = document[0].get_pixmap().tobytes("png")
    upload = authorized_client.post(
        "/api/media-assets/upload",
        files={"file": ("visual.png", image_bytes, "image/png")},
        data={"purpose": "scene_visual_upload"},
    )
    assert upload.status_code == 201
    asset = upload.json()
    body = {"scene_media": [{"scene_index": 0, "visual_asset_id": asset["id"]}]}
    blocked = authorized_client.post(
        f"/api/artifact-versions/{version_id}/media-renders", json=body
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "media_input_rights_unresolved"
    rights = authorized_client.patch(
        f"/api/media-assets/{asset['id']}/rights",
        json={
            "rights_basis": "user_owned",
            "consent_state": "not_applicable",
            "consent_required": False,
            "attribution": "Created for the test fixture.",
        },
    )
    assert rights.status_code == 200
    assert rights.json()["eligible_for_composition"] is True
    accepted = authorized_client.post(
        f"/api/artifact-versions/{version_id}/media-renders", json=body
    )
    assert accepted.status_code == 202
    assert accepted.json()["render_plan"]["scenes"][0]["visual_asset_hash"] == asset["content_hash"]

    def render_card(
        title: str, lines: list[str], *, visual_bytes: bytes | None = None
    ) -> tuple[bytes, int, int]:
        return b"fixture-frame:" + title.encode(), 1280, 720

    def compose(
        output_path: Path,
        scene_paths: list[Path],
        audio_paths: list[Path | None],
        durations_ms: list[int],
        workdir: Path,
    ) -> tuple[ProbeResult, int]:
        output_path.write_bytes(b"fixture-mp4-content")
        return ProbeResult(
            1280, 720, sum(durations_ms), 30.0, True, True, "fixture-ffmpeg/ffprobe", "mp4"
        ), len(scene_paths)

    monkeypatch.setattr("app.media_workflows.render_scene_card", render_card)
    monkeypatch.setattr("app.media_workflows.compose_mp4", compose)
    from app.media_worker import process_one_media_job

    render_id = accepted.json()["id"]
    for _ in range(4):
        assert process_one_media_job(factory, "rights-lineage-worker")
    ready = authorized_client.get(f"/api/media-renders/{render_id}").json()
    assert ready["status"] == "ready_for_review"
    with factory() as session:
        final_asset = session.scalar(
            select(MediaAsset).where(
                MediaAsset.render_id == render_id, MediaAsset.purpose == "final_mp4"
            )
        )
        assert final_asset is not None
        final_rights = session.scalar(
            select(MediaRightsRecord).where(MediaRightsRecord.media_asset_id == final_asset.id)
        )
        assert final_rights is not None
        assert final_rights.rights_basis == "derived"
        assert final_rights.consent_state == "not_applicable"


def test_source_media_upload_exposes_private_preview_locators_and_rights(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    document = fitz.open()
    document.new_page(width=100, height=80).draw_rect(fitz.Rect(10, 10, 60, 50), fill=(0, 0, 1))
    image_bytes: bytes = document[0].get_pixmap().tobytes("png")
    upload = authorized_client.post(
        "/api/sources/file",
        files={"file": ("source.png", image_bytes, "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["extraction_coverage"] == "unavailable"
    assert "extraction unavailable" in upload.json()["source_text"].lower()
    source_version_id = upload.json()["source_version_id"]
    saved = authorized_client.post(
        "/api/transformations",
        json={
            "source_text": upload.json()["source_text"],
            "source_version_id": source_version_id,
            "output_types": ["executive_summary"],
            "audience": "Community",
            "tone": "Clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "Inform",
            "style": "Plain language",
            "supporting_context": "",
        },
    )
    assert saved.status_code == 200
    pack = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    ).json()
    source_asset = next(
        item for item in pack["versions"][0]["assets"] if item["source_kind"] == "image"
    )
    assert source_asset["rights_basis"] == "unknown"
    assert source_asset["extraction_coverage"] == "unavailable"
    assert source_asset["preview_url"] == f"/api/source-assets/{source_asset['id']}/preview"
    assert "storage_key" not in source_asset
    assert authorized_client.get(source_asset["preview_url"]).content == image_bytes
    assert (
        authorized_client.get(source_asset["download_url"])
        .headers["content-disposition"]
        .startswith("attachment;")
    )
    update = authorized_client.patch(
        f"/api/source-assets/{source_asset['id']}/rights",
        json={
            "rights_basis": "user_owned",
            "consent_state": "not_applicable",
            "consent_required": False,
        },
    )
    assert update.status_code == 200
    with factory() as session:
        user = session.scalar(select(User).where(User.username == "subject_1"))
        assert user is not None
    from auth_support import login

    login(authorized_client, "source-media-other-owner")
    assert authorized_client.get(source_asset["preview_url"]).status_code == 404
    assert (
        authorized_client.patch(
            f"/api/source-assets/{source_asset['id']}/rights",
            json={
                "rights_basis": "user_owned",
                "consent_state": "not_applicable",
                "consent_required": False,
            },
        ).status_code
        == 404
    )


def test_media_worker_marks_an_expired_scene_lease_failed(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    version_id, _owner_id = _create_version(
        factory, "subject-1", "video_package", VIDEO.model_dump_json()
    )
    started = authorized_client.post(f"/api/artifact-versions/{version_id}/media-renders", json={})
    assert started.status_code == 202
    render_id = started.json()["id"]

    with factory() as session:
        stale_claim = claim_next_job(session, MEDIA_CPU, "stale-media-worker", lease_seconds=1)
        assert stale_claim is not None
        stale_job = session.get(Job, stale_claim.job_id)
        assert stale_job is not None
        stale_task_id = stale_job.media_task_id
        stale_job.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
        next_claim = claim_next_job(session, MEDIA_CPU, "recovery-media-worker", lease_seconds=30)
        assert next_claim is not None
        failed_job = session.get(Job, stale_claim.job_id)
        failed_task = session.get(MediaTask, stale_task_id)
        render = session.get(MediaRender, render_id)
        attempt = session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == stale_claim.job_id,
                JobAttempt.attempt_number == stale_claim.attempt_number,
            )
        )
        assert failed_job is not None and failed_job.status == "failed"
        assert failed_task is not None and failed_task.status == "failed"
        assert attempt is not None and attempt.status == "failed"
        assert render is not None and render.status == "partial_failure"


def test_media_storage_failure_leaves_no_derivative_rows(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    class FailingStore:
        def store(
            self, content: bytes, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES
        ) -> StoredPrivateAsset:
            raise AssetStorageError()

        def read(self, storage_key: str, *, max_bytes: int = MAX_PRIVATE_ASSET_BYTES) -> bytes:
            raise AssetStorageError()

        def delete(self, storage_key: str) -> None:
            return None

    _client, _engine, factory = auth_database
    version_id, _owner_id = _create_version(
        factory, "subject-1", "infographic", INFOGRAPHIC.model_dump_json()
    )
    started = authorized_client.post(f"/api/artifact-versions/{version_id}/media-renders", json={})
    assert started.status_code == 202

    with factory() as session:
        claim = claim_next_job(session, MEDIA_CPU, "storage-failure-worker")
    assert claim is not None

    from app.media_workflows import process_media_task

    assert process_media_task(factory, claim, FailingStore())
    with factory() as session:
        job = session.get(Job, claim.job_id)
        assert job is not None and job.media_task_id is not None
        task = session.get(MediaTask, job.media_task_id)
        render = session.get(MediaRender, started.json()["id"])
        assert task is not None and task.status == "failed"
        assert render is not None and render.status == "failed"
        assert not list(
            session.scalars(select(MediaAsset).where(MediaAsset.render_id == render.id))
        )


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="FFmpeg is installed in CI; local fixture check needs it"
)
def test_ffmpeg_fixture_composition_checks_video_audio_and_duration(tmp_path: Path) -> None:
    import wave

    image, _, _ = render_scene_card("Fixture scene", ["Not factual audio; fixture tone only"])
    scene = tmp_path / "scene.png"
    scene.write_bytes(image)
    tone = tmp_path / "fixture-tone.wav"
    with wave.open(str(tone), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(b"\x00\x00" * 24_000)
    output = tmp_path / "fixture.mp4"

    probe, count = compose_mp4(output, [scene], [tone], [3_000], tmp_path)

    assert count == 1
    assert probe.has_video and probe.has_audio
    assert (probe.width, probe.height) == (1280, 720)
    assert probe.fps == 30.0
    assert abs(probe.duration_ms - 3_000) <= 1_000
    assert output.stat().st_size > 0
