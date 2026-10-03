"""Narrow image and audio extraction capabilities plus bounded video sampling."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from app.media_renderer import MediaRenderError, probe_media_bytes, validate_image_bytes
from app.source_versions import SourceRegionInput

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4_000
MAX_IMAGE_PIXELS = 16_000_000
MAX_AUDIO_DURATION_MS = 60_000
MAX_VIDEO_DURATION_MS = 180_000
VIDEO_FRAME_INTERVAL_MS = 5_000
MAX_VIDEO_SAMPLED_FRAMES = 36
MAX_EXTRACTED_TEXT_CHARS = 20_000
MAX_TRANSCRIPT_SEGMENTS = 200


class MediaSourceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VisionRegion(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    kind: Literal["text", "description"] = "text"
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def valid_normalized_bbox(self) -> VisionRegion:
        if self.bbox is not None:
            x, y, width, height = self.bbox
            if (
                min(x, y, width, height) < 0
                or max(x, y, width, height) > 1
                or x + width > 1
                or y + height > 1
            ):
                raise ValueError("Vision bounding boxes must be normalized to the image")
        return self


class ImageExtractionResult(BaseModel):
    regions: list[VisionRegion] = Field(max_length=100)
    coverage: Literal["complete", "partial"]
    profile: str = Field(default="unversioned_candidate", max_length=80)


class TranscriptSegment(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self) -> TranscriptSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("Transcript segments need a positive time range")
        return self


class AudioExtractionResult(BaseModel):
    segments: list[TranscriptSegment] = Field(max_length=MAX_TRANSCRIPT_SEGMENTS)
    coverage: Literal["complete", "partial"]
    profile: str = Field(default="unversioned_candidate", max_length=80)


class VisionExtractor(Protocol):
    """Provider-neutral bounded image text/description extraction contract."""

    def extract(self, image_bytes: bytes) -> ImageExtractionResult: ...


class ASRExtractor(Protocol):
    """Provider-neutral bounded timestamped speech extraction contract."""

    def transcribe(self, audio_bytes: bytes) -> AudioExtractionResult: ...


def get_vision_extractor() -> VisionExtractor | None:
    """No live vision provider is configured."""
    return None


def get_asr_extractor() -> ASRExtractor | None:
    """No live ASR provider is configured."""
    return None


@dataclass(frozen=True, slots=True)
class MediaSourceExtraction:
    media_type: str
    source_text: str
    method: str
    coverage: Literal["complete", "partial", "unavailable"]
    details: dict[str, object]
    regions: tuple[SourceRegionInput, ...]
    storage_max_bytes: int


def extract_source_media(
    extension: str,
    content: bytes,
    *,
    vision: VisionExtractor | None = None,
    asr: ASRExtractor | None = None,
) -> MediaSourceExtraction:
    """Validate media bytes, run configured extraction, and retain explicit coverage."""
    if extension in {"png", "jpg", "jpeg"}:
        return _extract_image(extension, content, vision)
    if extension in {"wav", "mp3", "m4a"}:
        return _extract_audio(extension, content, asr)
    if extension == "mp4":
        return _extract_video(content, vision, asr)
    raise MediaSourceError("unsupported_media_format")


def _extract_image(
    extension: str, content: bytes, vision: VisionExtractor | None
) -> MediaSourceExtraction:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise MediaSourceError("image_file_too_large")
    try:
        width, height = validate_image_bytes(
            content,
            extension,
            max_dimension=MAX_IMAGE_DIMENSION,
            max_pixels=MAX_IMAGE_PIXELS,
        )
    except MediaRenderError as error:
        raise MediaSourceError(error.code) from None
    media_type = "image/png" if extension == "png" else "image/jpeg"
    if vision is None:
        return MediaSourceExtraction(
            media_type,
            "[Image extraction unavailable: no vision provider is configured.]",
            "vision_not_configured",
            "unavailable",
            {"vision_status": "not_configured", "image_dimensions": [width, height]},
            (),
            MAX_IMAGE_BYTES,
        )
    try:
        result = ImageExtractionResult.model_validate(vision.extract(content))
    except Exception:
        raise MediaSourceError("vision_extraction_failed") from None
    regions = tuple(
        SourceRegionInput(
            locator=f"image:region:{index}",
            region_type="image_ocr" if item.kind == "text" else "image_description",
            locator_kind="image_region",
            locator_metadata={"bbox_normalized": list(item.bbox)} if item.bbox else None,
            text=item.text,
        )
        for index, item in enumerate(result.regions, 1)
    )
    projection = _bounded_projection(
        [f"[Image region {index}] {item.text}" for index, item in enumerate(result.regions, 1)],
        "[Image has no extractable text or description.]",
    )
    return MediaSourceExtraction(
        media_type,
        projection,
        f"vision:{result.profile}",
        result.coverage,
        {"vision_status": "available", "vision_coverage": result.coverage},
        regions,
        MAX_IMAGE_BYTES,
    )


def _extract_audio(
    extension: str, content: bytes, asr: ASRExtractor | None
) -> MediaSourceExtraction:
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise MediaSourceError("audio_file_too_large")
    try:
        probe = probe_media_bytes(content, extension, max_duration_ms=MAX_AUDIO_DURATION_MS)
    except MediaRenderError as error:
        raise MediaSourceError(error.code) from None
    if probe.has_video or not probe.has_audio:
        raise MediaSourceError("invalid_audio_stream")
    formats = set(probe.format_name.split(","))
    permitted_formats = {
        "wav": {"wav"},
        "mp3": {"mp3"},
        "m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    }
    if not formats.intersection(permitted_formats[extension]):
        raise MediaSourceError("audio_container_mismatch")
    media_type = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4"}[extension]
    if asr is None:
        return MediaSourceExtraction(
            media_type,
            "[Audio transcription unavailable: no ASR provider is configured.]",
            "asr_not_configured",
            "unavailable",
            {"asr_status": "not_configured", "duration_ms": probe.duration_ms},
            (),
            MAX_AUDIO_BYTES,
        )
    try:
        result = AudioExtractionResult.model_validate(asr.transcribe(content))
        segments = _checked_transcript_segments(result.segments, probe.duration_ms)
    except Exception:
        raise MediaSourceError("asr_extraction_failed") from None
    regions, lines = _audio_regions(segments, prefix="audio")
    projection = _bounded_projection(
        lines, "[Audio contained no transcribed speech in the extracted coverage.]"
    )
    return MediaSourceExtraction(
        media_type,
        projection,
        f"asr:{result.profile}",
        result.coverage,
        {
            "asr_status": "available",
            "asr_coverage": result.coverage,
            "duration_ms": probe.duration_ms,
        },
        regions,
        MAX_AUDIO_BYTES,
    )


def _extract_video(
    content: bytes,
    vision: VisionExtractor | None,
    asr: ASRExtractor | None,
) -> MediaSourceExtraction:
    if not content or len(content) > MAX_VIDEO_BYTES:
        raise MediaSourceError("video_file_too_large")
    try:
        probe = probe_media_bytes(content, "mp4", max_duration_ms=MAX_VIDEO_DURATION_MS)
    except MediaRenderError as error:
        raise MediaSourceError(error.code) from None
    if not probe.has_video:
        raise MediaSourceError("invalid_video_stream")
    if not {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}.intersection(probe.format_name.split(",")):
        raise MediaSourceError("video_container_mismatch")
    visual_regions: list[SourceRegionInput] = []
    sampled_timestamps: list[int] = []
    transcript_regions: tuple[SourceRegionInput, ...] = ()
    transcript_lines: list[str] = []
    asr_status = "not_present" if not probe.has_audio else "not_configured"
    asr_coverage: str | None = None
    frame_bytes = _sample_video_frames(content)
    for index, frame in enumerate(frame_bytes):
        timestamp_ms = index * VIDEO_FRAME_INTERVAL_MS
        sampled_timestamps.append(timestamp_ms)
        if vision is None:
            visual_regions.append(
                SourceRegionInput(
                    locator=f"video:frame:{timestamp_ms:09d}",
                    region_type="video_frame_sample",
                    locator_kind="video_frame",
                    locator_metadata={"timestamp_ms": timestamp_ms},
                    text=None,
                )
            )
            continue
        try:
            result = ImageExtractionResult.model_validate(vision.extract(frame))
        except Exception:
            raise MediaSourceError("vision_extraction_failed") from None
        for region_index, region in enumerate(result.regions, 1):
            metadata: dict[str, object] = {"timestamp_ms": timestamp_ms}
            if region.bbox is not None:
                metadata["bbox_normalized"] = list(region.bbox)
            visual_regions.append(
                SourceRegionInput(
                    locator=f"video:frame:{timestamp_ms:09d}:region:{region_index}",
                    region_type="video_frame_text"
                    if region.kind == "text"
                    else "video_frame_description",
                    locator_kind="video_frame",
                    locator_metadata=metadata,
                    text=region.text,
                )
            )
    if probe.has_audio and asr is not None:
        audio_bytes = _extract_video_audio(content)
        try:
            audio_result = AudioExtractionResult.model_validate(asr.transcribe(audio_bytes))
            segments = _checked_transcript_segments(audio_result.segments, probe.duration_ms)
        except Exception:
            raise MediaSourceError("asr_extraction_failed") from None
        transcript_regions, transcript_lines = _audio_regions(segments, prefix="video:audio")
        asr_status = "available"
        asr_coverage = audio_result.coverage

    regions = (*transcript_regions, *visual_regions)
    text_lines = [
        *transcript_lines,
        *(f"[Video frame] {region.text}" for region in visual_regions if region.text),
    ]
    has_text = bool(text_lines)
    coverage: Literal["partial", "unavailable"] = "partial" if has_text else "unavailable"
    projection = _bounded_projection(
        text_lines,
        "[Video extraction unavailable: sampled frames are locators only; no vision or ASR "
        "provider is configured.]",
    )
    return MediaSourceExtraction(
        "video/mp4",
        projection,
        "video_sampled_frames_and_optional_asr",
        coverage,
        {
            "duration_ms": probe.duration_ms,
            "dimensions": [probe.width, probe.height],
            "sample_interval_ms": VIDEO_FRAME_INTERVAL_MS,
            "sampled_timestamps_ms": sampled_timestamps,
            "visual_frame_coverage": "sampled_partial",
            "vision_status": "available" if vision is not None else "not_configured",
            "asr_status": asr_status,
            "asr_coverage": asr_coverage,
        },
        tuple(regions),
        MAX_VIDEO_BYTES,
    )


def _sample_video_frames(content: bytes) -> list[bytes]:
    try:
        with tempfile.TemporaryDirectory(prefix="axiomweave-video-source-") as directory:
            folder = Path(directory)
            source_path = folder / "source.mp4"
            source_path.write_bytes(content)
            pattern = folder / "frame_%03d.jpg"
            _run_ffmpeg(
                [
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source_path),
                    "-vf",
                    f"fps=1/{VIDEO_FRAME_INTERVAL_MS / 1000:.0f},scale=640:-2",
                    "-frames:v",
                    str(MAX_VIDEO_SAMPLED_FRAMES),
                    "-q:v",
                    "3",
                    str(pattern),
                ],
                timeout=90,
                cwd=folder,
            )
            frames = sorted(folder.glob("frame_*.jpg"))
            if not frames:
                raise MediaSourceError("video_frame_extraction_failed")
            return [frame.read_bytes() for frame in frames]
    except MediaSourceError:
        raise
    except Exception:
        raise MediaSourceError("video_frame_extraction_failed") from None


def _extract_video_audio(content: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="axiomweave-video-audio-") as directory:
        folder = Path(directory)
        source_path = folder / "source.mp4"
        output_path = folder / "audio.wav"
        source_path.write_bytes(content)
        _run_ffmpeg(
            [
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-t",
                str(MAX_VIDEO_DURATION_MS / 1000),
                "-f",
                "wav",
                str(output_path),
            ],
            timeout=90,
            cwd=folder,
        )
        try:
            return output_path.read_bytes()
        except OSError:
            raise MediaSourceError("video_audio_extraction_failed") from None


def _run_ffmpeg(args: list[str], *, timeout: int, cwd: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise MediaSourceError("ffmpeg_unavailable")
    try:
        result = subprocess.run(
            [executable, *args],
            cwd=cwd,
            shell=False,
            check=False,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        raise MediaSourceError("ffmpeg_timeout") from None
    except OSError:
        raise MediaSourceError("ffmpeg_unavailable") from None
    if result.returncode != 0:
        raise MediaSourceError("ffmpeg_failed")


def _checked_transcript_segments(
    segments: list[TranscriptSegment], duration_ms: int
) -> list[TranscriptSegment]:
    previous_start = -1
    for segment in segments:
        if segment.start_ms < previous_start or segment.end_ms > duration_ms:
            raise MediaSourceError("asr_timing_invalid")
        previous_start = segment.start_ms
    return segments


def _audio_regions(
    segments: list[TranscriptSegment], *, prefix: str
) -> tuple[tuple[SourceRegionInput, ...], list[str]]:
    regions: list[SourceRegionInput] = []
    lines: list[str] = []
    for segment in segments:
        locator = f"{prefix}:{segment.start_ms:09d}-{segment.end_ms:09d}"
        regions.append(
            SourceRegionInput(
                locator=locator,
                region_type="audio_transcript",
                locator_kind="audio_time_range",
                locator_metadata={
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                },
                text=segment.text,
            )
        )
        lines.append(
            f"[{_format_time(segment.start_ms)}–{_format_time(segment.end_ms)}] {segment.text}"
        )
    return tuple(regions), lines


def _bounded_projection(lines: list[str], fallback: str) -> str:
    projection = "\n\n".join(lines) if lines else fallback
    if len(projection) > MAX_EXTRACTED_TEXT_CHARS:
        raise MediaSourceError("extracted_text_too_large")
    return projection


def _format_time(milliseconds: int) -> str:
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
