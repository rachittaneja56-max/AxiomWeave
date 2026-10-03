from typing import Any

import fitz as _fitz  # pyright: ignore[reportMissingTypeStubs]
import pytest

from app import multimodal_extraction as extraction
from app.media_renderer import ProbeResult
from app.multimodal_extraction import (
    AudioExtractionResult,
    ImageExtractionResult,
    MediaSourceError,
    TranscriptSegment,
    VisionRegion,
    extract_source_media,
)

fitz: Any = _fitz


def _png_fixture() -> bytes:
    document = fitz.open()
    document.new_page(width=120, height=90)
    image_bytes: bytes = document[0].get_pixmap().tobytes("png")
    return image_bytes


class FixtureVision:
    def extract(self, image_bytes: bytes) -> ImageExtractionResult:
        return ImageExtractionResult(
            regions=[
                VisionRegion(
                    text="Doors open Friday.",
                    kind="text",
                    bbox=(0.1, 0.2, 0.6, 0.2),
                )
            ],
            coverage="partial",
            profile="fixture-vision-v1",
        )


class FixtureAsr:
    def transcribe(self, audio_bytes: bytes) -> AudioExtractionResult:
        return AudioExtractionResult(
            segments=[TranscriptSegment(text="Doors open Friday.", start_ms=500, end_ms=1_600)],
            coverage="partial",
            profile="fixture-asr-v1",
        )


def _audio_probe(duration_ms: int = 2_000) -> ProbeResult:
    return ProbeResult(None, None, duration_ms, None, False, True, "fixture-ffprobe", "wav")


def _video_probe(duration_ms: int = 10_000) -> ProbeResult:
    return ProbeResult(
        640,
        360,
        duration_ms,
        30.0,
        True,
        True,
        "fixture-ffprobe",
        "mov,mp4,m4a,3gp,3g2,mj2",
    )


def test_image_extraction_uses_normalized_bounding_box_locators() -> None:
    result = extract_source_media("png", _png_fixture(), vision=FixtureVision())

    assert result.coverage == "partial"
    assert result.details["vision_status"] == "available"
    assert result.source_text == "[Image region 1] Doors open Friday."
    assert len(result.regions) == 1
    assert result.regions[0].locator_kind == "image_region"
    assert result.regions[0].locator_metadata == {"bbox_normalized": [0.1, 0.2, 0.6, 0.2]}


def test_audio_extraction_keeps_timestamped_asr_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def audio_probe(content: bytes, suffix: str, *, max_duration_ms: int) -> ProbeResult:
        return _audio_probe()

    monkeypatch.setattr(extraction, "probe_media_bytes", audio_probe)

    result = extract_source_media("wav", b"fixture audio bytes", asr=FixtureAsr())

    assert result.coverage == "partial"
    assert result.details["asr_status"] == "available"
    assert result.regions[0].locator == "audio:000000500-000001600"
    assert result.regions[0].locator_metadata == {"start_ms": 500, "end_ms": 1_600}
    assert result.regions[0].text == "Doors open Friday."


def test_video_extraction_maps_frame_and_audio_locators_to_their_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def video_probe(content: bytes, suffix: str, *, max_duration_ms: int) -> ProbeResult:
        return _video_probe()

    monkeypatch.setattr(extraction, "probe_media_bytes", video_probe)

    def sample_video_frames(content: bytes) -> list[bytes]:
        return [b"frame-a", b"frame-b"]

    monkeypatch.setattr(extraction, "_sample_video_frames", sample_video_frames)

    def video_audio(content: bytes) -> bytes:
        return b"fixture wav"

    monkeypatch.setattr(extraction, "_extract_video_audio", video_audio)

    result = extract_source_media(
        "mp4", b"fixture video bytes", vision=FixtureVision(), asr=FixtureAsr()
    )

    assert result.coverage == "partial"
    assert result.details["sampled_timestamps_ms"] == [0, 5_000]
    assert result.details["visual_frame_coverage"] == "sampled_partial"
    assert result.details["asr_status"] == "available"
    assert result.regions[0].locator == "video:audio:000000500-000001600"
    assert result.regions[0].locator_metadata == {"start_ms": 500, "end_ms": 1_600}
    assert result.regions[1].locator == "video:frame:000000000:region:1"
    assert result.regions[1].locator_metadata == {
        "timestamp_ms": 0,
        "bbox_normalized": [0.1, 0.2, 0.6, 0.2],
    }
    assert result.regions[2].locator == "video:frame:000005000:region:1"


def test_unavailable_video_extraction_keeps_frame_locators_without_claim_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def video_probe(content: bytes, suffix: str, *, max_duration_ms: int) -> ProbeResult:
        return _video_probe()

    monkeypatch.setattr(extraction, "probe_media_bytes", video_probe)

    def sample_video_frames(content: bytes) -> list[bytes]:
        return [b"frame-a"]

    monkeypatch.setattr(extraction, "_sample_video_frames", sample_video_frames)

    result = extract_source_media("mp4", b"fixture video bytes")

    assert result.coverage == "unavailable"
    assert result.regions[0].locator == "video:frame:000000000"
    assert result.regions[0].text is None
    assert "no vision or ASR" in result.source_text


def test_invalid_vision_bbox_is_rejected_as_provider_output() -> None:
    class InvalidVision:
        def extract(self, image_bytes: bytes) -> ImageExtractionResult:
            return ImageExtractionResult(
                regions=[VisionRegion(text="Invalid", bbox=(0.8, 0.2, 0.4, 0.3))],
                coverage="complete",
            )

    with pytest.raises(MediaSourceError, match="vision_extraction_failed"):
        extract_source_media("png", _png_fixture(), vision=InvalidVision())
