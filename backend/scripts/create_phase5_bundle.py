"""Create deterministic media previews and a human-review bundle without external providers."""

from __future__ import annotations

import argparse
import json
import time
from hashlib import sha256
from pathlib import Path

import fitz

from app.artifact_contracts import InfographicSpec, VideoPackageSpec
from app.media_renderer import (
    VIDEO_PROFILE,
    VIDEO_RENDERER_VERSION,
    compose_mp4,
    infographic_spec_from_content,
    render_infographic,
    render_scene_card,
    video_spec_from_content,
    webvtt_for_plan,
)

SOURCE_TEXT = "Doors open Friday at 09:30 in Hall A."
INFOGRAPHIC_JSON = {
    "title": "Community open day",
    "subtitle": "Demonstration media fixture",
    "key_message": "Doors open Friday at 09:30 in Hall A.",
    "blocks": [
        {"type": "section", "heading": "When", "body": "Doors open Friday."},
        {
            "type": "callout",
            "label": "Opening time",
            "value": "09:30",
            "explanation": "The source statement gives this time.",
        },
        {
            "type": "data",
            "heading": "Location",
            "rows": [{"label": "Entrance", "value": "Hall A", "note": ""}],
        },
    ],
    "visual_direction": "Simple green and cream cards",
}
VIDEO_JSON = {
    "title": "Community open day",
    "concept": "A deterministic visual fixture using only the supplied source sentence.",
    "scenes": [
        {
            "title": "Friday",
            "narration": "Doors open Friday.",
            "on_screen_text": ["Friday"],
            "visual_direction": "Deterministic scene card",
            "transition_notes": "Hard cut",
        },
        {
            "title": "09:30 · Hall A",
            "narration": "Doors open at 09:30 in Hall A.",
            "on_screen_text": ["09:30", "Hall A"],
            "visual_direction": "Deterministic scene card",
            "transition_notes": "Hard cut",
        },
    ],
}


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def create_bundle(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    infographic = InfographicSpec.model_validate(INFOGRAPHIC_JSON)
    video = VideoPackageSpec.model_validate(VIDEO_JSON)
    infographic_path = output_dir / "infographic-spec.json"
    video_path = output_dir / "video-package-spec.json"
    _write_json(infographic_path, infographic.model_dump(mode="json"))
    _write_json(video_path, video.model_dump(mode="json"))
    video = video_spec_from_content(video_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    svg, png, width, height = render_infographic(
        infographic_spec_from_content(infographic_path.read_text(encoding="utf-8"))
    )
    infographic_elapsed_ms = round((time.perf_counter() - started) * 1_000)
    svg_path = output_dir / "infographic.svg"
    png_path = output_dir / "infographic.png"
    svg_path.write_bytes(svg)
    png_path.write_bytes(png)

    scene_paths: list[Path] = []
    durations_ms: list[int] = []
    plan_scenes: list[dict[str, object]] = []
    for index, scene in enumerate(video.scenes):
        frame, scene_width, scene_height = render_scene_card(scene.title, scene.on_screen_text)
        frame_path = output_dir / f"video-scene-{index + 1:02d}.png"
        frame_path.write_bytes(frame)
        scene_paths.append(frame_path)
        duration_ms = 4_000
        durations_ms.append(duration_ms)
        plan_scenes.append(
            {
                "scene_index": index,
                "title": scene.title,
                "narration": scene.narration,
                "on_screen_text": scene.on_screen_text,
                "duration_ms": duration_ms,
                "timing_method": "human_review_fixture_fixed_timing",
                "width": scene_width,
                "height": scene_height,
                "audio_coverage": "none",
            }
        )
    video_plan = {
        "artifact_version": "human-review-fixture-v1",
        "renderer_profile": VIDEO_PROFILE,
        "renderer_version": VIDEO_RENDERER_VERSION,
        "scenes": plan_scenes,
        "audio_coverage": "none",
        "audio_policy": "silent fixture; no narration audio generated",
    }
    plan_path = output_dir / "video-render-plan.json"
    _write_json(plan_path, video_plan)
    vtt_path = output_dir / "captions.vtt"
    vtt_path.write_bytes(webvtt_for_plan(video_plan))
    mp4_path = output_dir / "video.mp4"
    started = time.perf_counter()
    probe, scene_count = compose_mp4(
        mp4_path,
        scene_paths,
        [None] * len(scene_paths),
        durations_ms,
        output_dir,
    )
    video_elapsed_ms = round((time.perf_counter() - started) * 1_000)
    if not probe.has_video or not probe.has_audio:
        raise RuntimeError("FFprobe did not find the expected video and silent audio streams")
    if probe.duration_ms != sum(durations_ms):
        raise RuntimeError("FFprobe duration does not match the fixture plan")

    provenance = {
        "note": "Synthetic test fixture, not a production artifact.",
        "source_text": SOURCE_TEXT,
        "source_text_sha256": sha256(SOURCE_TEXT.encode("utf-8")).hexdigest(),
        "artifact_specs": {
            "infographic": "infographic-spec.json",
            "video_package": "video-package-spec.json",
        },
        "factual_content_policy": (
            "Fixture labels repeat the one supplied sentence; scene cards add no facts."
        ),
        "ai_generation_provider": None,
    }
    provenance_path = output_dir / "provenance.json"
    _write_json(provenance_path, provenance)

    checklist_path = output_dir / "HUMAN_REVIEW_CHECKLIST.md"
    checklist_path.write_text(
        "# Phase 5 media fixture review\n\n"
        "Automated bundle generated without an AI image, video, vision, ASR, or TTS provider.\n\n"
        "## Infographic\n\n"
        "- [ ] Readable at full size and normal display scale\n"
        "- [ ] Text hierarchy, spacing, and contrast are acceptable\n"
        "- [ ] Every displayed value matches the editable fixture spec\n\n"
        "## Video\n\n"
        "- [ ] Playback is smooth and scene changes are clear\n"
        "- [ ] Scene timing and captions are legible and aligned\n"
        "- [ ] Silent audio track is expected; narration audio was not generated\n\n"
        "## Provenance and review\n\n"
        "- [ ] Rendered text remains within the fixture source sentence\n"
        "- [ ] Media approval is limited to layout, legibility, timing, and media quality\n"
        "- [ ] Factual evidence review remains separate\n\n"
        "Human review status: **PENDING**.\n",
        encoding="utf-8",
    )

    files = [
        infographic_path,
        video_path,
        plan_path,
        provenance_path,
        checklist_path,
        svg_path,
        png_path,
        vtt_path,
        mp4_path,
        *scene_paths,
    ]
    metrics = {
        "fixture": True,
        "human_review_status": "pending",
        "renderer": "axiomweave-media-v1",
        "pymupdf_version": str(fitz.VersionBind),
        "ffmpeg_ffprobe": probe.tool_version,
        "infographic": {
            "width": width,
            "height": height,
            "elapsed_ms": infographic_elapsed_ms,
            "output_bytes": svg_path.stat().st_size + png_path.stat().st_size,
        },
        "video": {
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "duration_ms": probe.duration_ms,
            "scene_count": scene_count,
            "audio_coverage": "none",
            "audio_stream_present": probe.has_audio,
            "elapsed_ms": video_elapsed_ms,
            "output_bytes": mp4_path.stat().st_size,
            "captions_bytes": vtt_path.stat().st_size,
        },
        "external_api_cost": 0,
        "bundle_storage_bytes_excluding_metrics": sum(path.stat().st_size for path in files),
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)} for path in files
        },
    }
    _write_json(output_dir / "metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    metrics = create_bundle(args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "human_review_status": metrics["human_review_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
