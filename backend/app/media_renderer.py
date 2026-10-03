"""Bounded deterministic rendering helpers for finished media derivatives."""

from __future__ import annotations

import base64
import html
import json
import math
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz as _fitz  # pyright: ignore[reportMissingTypeStubs]

from app.artifact_contracts import (
    InfographicCalloutBlock,
    InfographicSectionBlock,
    InfographicSpec,
    VideoPackageSpec,
)

fitz: Any = _fitz

INFOGRAPHIC_PROFILE = "axiomweave-infographic-portrait-v1"
INFOGRAPHIC_RENDERER_VERSION = "1.0.0"
VIDEO_PROFILE = "axiomweave-video-720p-v1"
VIDEO_RENDERER_VERSION = "1.0.0"
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30
MAX_INFOGRAPHIC_HEIGHT = 8_000
MAX_VIDEO_DURATION_MS = 180_000
MAX_VIDEO_BYTES = 256 * 1024 * 1024
FFMPEG_TIMEOUT_SECONDS = 180
FFPROBE_TIMEOUT_SECONDS = 30


class MediaRenderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_image_bytes(
    content: bytes,
    suffix: str,
    *,
    max_dimension: int,
    max_pixels: int,
) -> tuple[int, int]:
    """Read image dimensions before decoding so oversized raster inputs stay bounded."""
    if suffix == "png":
        if (
            len(content) < 24
            or not content.startswith(b"\x89PNG\r\n\x1a\n")
            or content[12:16] != b"IHDR"
        ):
            raise MediaRenderError("invalid_image")
        width, height = struct.unpack(">II", content[16:24])
    elif suffix in {"jpg", "jpeg"}:
        if not content.startswith(b"\xff\xd8\xff"):
            raise MediaRenderError("invalid_image")
        offset = 2
        dimensions: tuple[int, int] | None = None
        frame_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while offset + 4 <= len(content):
            if content[offset] != 0xFF:
                offset += 1
                continue
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                break
            marker = content[offset]
            offset += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if offset + 2 > len(content):
                break
            segment_length = int.from_bytes(content[offset : offset + 2], "big")
            if segment_length < 2 or offset + segment_length > len(content):
                break
            if marker in frame_markers and segment_length >= 7:
                height = int.from_bytes(content[offset + 3 : offset + 5], "big")
                width = int.from_bytes(content[offset + 5 : offset + 7], "big")
                dimensions = (width, height)
                break
            offset += segment_length
        if dimensions is None:
            raise MediaRenderError("invalid_image")
        width, height = dimensions
    else:
        raise MediaRenderError("unsupported_image_format")

    if width <= 0 or height <= 0 or width > max_dimension or height > max_dimension:
        raise MediaRenderError("image_dimensions_out_of_range")
    if width * height > max_pixels:
        raise MediaRenderError("image_dimensions_out_of_range")
    try:
        pixmap = fitz.Pixmap(content)
    except Exception:
        raise MediaRenderError("invalid_image") from None
    if pixmap.width != width or pixmap.height != height:
        raise MediaRenderError("invalid_image")
    return width, height


@dataclass(frozen=True, slots=True)
class ProbeResult:
    width: int | None
    height: int | None
    duration_ms: int
    fps: float | None
    has_video: bool
    has_audio: bool
    tool_version: str
    format_name: str


def canonical_hash(value: object) -> str:
    from hashlib import sha256

    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    line = ""
    for word in words:
        while len(word) > max_chars:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{line} {word}".strip()
        if len(candidate) > max_chars and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def infographic_svg(spec: InfographicSpec) -> tuple[bytes, int, int]:
    """Lay out source text into a safe static SVG without deriving new factual values."""
    width = 1080
    margin = 72
    inner_width = width - 2 * margin
    records: list[tuple[str, list[str], str]] = []
    y = 0
    header_lines = _wrap(spec.title, 28)
    y += max(1, len(header_lines)) * 62 + 26
    if spec.subtitle:
        y += len(_wrap(spec.subtitle, 58)) * 30 + 22
    if spec.key_message:
        y += len(_wrap(spec.key_message, 58)) * 30 + 74
    else:
        y += 42

    for block in spec.blocks:
        if isinstance(block, InfographicSectionBlock):
            lines = _wrap(block.body, 62)
            cost = 54 + len(lines) * 30 + 44
            records.append(("section", [block.heading, *lines], f"s{len(records)}"))
        elif isinstance(block, InfographicCalloutBlock):
            lines = _wrap(block.explanation, 56) if block.explanation else []
            cost = 62 + 36 + len(lines) * 28 + 46
            records.append(("callout", [block.label, block.value, *lines], f"s{len(records)}"))
        else:
            rendered_rows = [
                line
                for row in block.rows
                for line in _wrap(
                    f"{row.label}: {row.value}" + (f" ({row.note})" if row.note else ""),
                    62,
                )
            ]
            cost = 54 + 38 + len(rendered_rows) * 30 + 42
            records.append(("data", [block.heading, *rendered_rows], f"s{len(records)}"))
        y += cost
    direction_lines = _wrap(f"Visual direction: {spec.visual_direction}", 90)
    y += len(direction_lines) * 24 + 86
    height = max(1350, y)
    if height > MAX_INFOGRAPHIC_HEIGHT:
        raise MediaRenderError("infographic_content_exceeds_layout_limit")

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        '<rect width="100%" height="100%" fill="#f5f2eb"/>',
        '<rect x="24" y="24" width="1032" height="1032" rx="30" fill="#173b3b"/>',
    ]
    cursor = 100
    for line in header_lines:
        out.append(
            f'<text x="{margin}" y="{cursor}" fill="#ffffff" font-family="sans-serif" '
            f'font-size="52" font-weight="700">{html.escape(line)}</text>'
        )
        cursor += 62
    if spec.subtitle:
        cursor += 8
        for line in _wrap(spec.subtitle, 58):
            out.append(
                f'<text x="{margin}" y="{cursor}" fill="#c9dfd7" font-family="sans-serif" '
                f'font-size="24">{html.escape(line)}</text>'
            )
            cursor += 30
    if spec.key_message:
        cursor += 18
        key_lines = _wrap(spec.key_message, 58)
        box_h = 26 + 30 * len(key_lines)
        out.append(
            f'<rect x="{margin}" y="{cursor - 22}" width="{inner_width}" height="{box_h}" '
            'rx="16" fill="#d4ede2"/>'
        )
        for line in key_lines:
            out.append(
                f'<text x="{margin + 24}" y="{cursor}" fill="#173b3b" '
                f'font-family="sans-serif" font-size="23" font-weight="600">'
                f"{html.escape(line)}</text>"
            )
            cursor += 30
        cursor += 50
    else:
        cursor += 30

    for block in spec.blocks:
        card_y = cursor - 26
        card_h = 0
        if isinstance(block, InfographicSectionBlock):
            heading_lines = _wrap(block.heading, 48)
            body_lines = _wrap(block.body, 62)
            card_h = 42 + 32 * len(heading_lines) + 28 * len(body_lines)
            out.append(
                f'<rect x="{margin}" y="{card_y}" width="{inner_width}" height="{card_h}" '
                'rx="18" fill="#ffffff"/>'
            )
            text_y = cursor + 10
            for line in heading_lines:
                out.append(
                    f'<text x="{margin + 26}" y="{text_y}" fill="#173b3b" '
                    f'font-family="sans-serif" font-size="27" font-weight="700">'
                    f"{html.escape(line)}</text>"
                )
                text_y += 32
            for line in body_lines:
                out.append(
                    f'<text x="{margin + 26}" y="{text_y}" fill="#243535" '
                    f'font-family="sans-serif" font-size="22">{html.escape(line)}</text>'
                )
                text_y += 28
            cursor = card_y + card_h + 28
        elif isinstance(block, InfographicCalloutBlock):
            explanation_lines = _wrap(block.explanation, 56) if block.explanation else []
            card_h = 120 + len(explanation_lines) * 27
            out.append(
                f'<rect x="{margin}" y="{card_y}" width="{inner_width}" height="{card_h}" '
                'rx="18" fill="#f5dfb1"/>'
            )
            out.append(
                f'<text x="{margin + 26}" y="{cursor + 10}" fill="#694900" '
                f'font-family="sans-serif" font-size="21" font-weight="700">'
                f"{html.escape(block.label)}</text>"
            )
            out.append(
                f'<text x="{margin + 26}" y="{cursor + 52}" fill="#352600" '
                f'font-family="sans-serif" font-size="34" font-weight="700">'
                f"{html.escape(block.value)}</text>"
            )
            text_y = cursor + 88
            for line in explanation_lines:
                out.append(
                    f'<text x="{margin + 26}" y="{text_y}" fill="#352600" '
                    f'font-family="sans-serif" font-size="21">{html.escape(line)}</text>'
                )
                text_y += 27
            cursor = card_y + card_h + 28
        else:
            heading_lines = _wrap(block.heading, 48)
            rows = [
                line
                for row in block.rows
                for line in _wrap(
                    f"{row.label}: {row.value}" + (f" ({row.note})" if row.note else ""),
                    62,
                )
            ]
            card_h = 38 + len(heading_lines) * 32 + len(rows) * 34
            out.append(
                f'<rect x="{margin}" y="{card_y}" width="{inner_width}" height="{card_h}" '
                'rx="18" fill="#ffffff"/>'
            )
            text_y = cursor + 8
            for line in heading_lines:
                out.append(
                    f'<text x="{margin + 26}" y="{text_y}" fill="#173b3b" '
                    f'font-family="sans-serif" font-size="27" font-weight="700">'
                    f"{html.escape(line)}</text>"
                )
                text_y += 32
            for row_index, line in enumerate(rows):
                color = "#ebf3ef" if row_index % 2 == 0 else "#ffffff"
                out.append(
                    f'<rect x="{margin + 14}" y="{text_y - 24}" '
                    f'width="{inner_width - 28}" height="32" rx="8" fill="{color}"/>'
                )
                out.append(
                    f'<text x="{margin + 26}" y="{text_y}" fill="#243535" '
                    f'font-family="sans-serif" font-size="21">{html.escape(line)}</text>'
                )
                text_y += 34
            cursor = card_y + card_h + 28

    cursor += 10
    for line in direction_lines:
        out.append(
            f'<text x="{margin}" y="{cursor}" fill="#52615d" font-family="sans-serif" '
            f'font-size="17">{html.escape(line)}</text>'
        )
        cursor += 24
    out.append("</svg>")
    return "\n".join(out).encode("utf-8"), width, height


def svg_to_png(svg: bytes, width: int, height: int) -> bytes:
    try:
        svg_document = fitz.open(stream=svg, filetype="svg")
        pdf_bytes = svg_document.convert_to_pdf()
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = pdf[0]
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(width / page.rect.width, height / page.rect.height), alpha=False
        )
        result = pixmap.tobytes("png")
    except Exception:
        raise MediaRenderError("png_rasterization_failed") from None
    if not result.startswith(b"\x89PNG\r\n\x1a\n") or not result:
        raise MediaRenderError("png_validation_failed")
    return result


def render_infographic(spec: InfographicSpec) -> tuple[bytes, bytes, int, int]:
    svg, width, height = infographic_svg(spec)
    png = svg_to_png(svg, width, height)
    return svg, png, width, height


def deterministic_scene_duration_ms(scene_text: str) -> int:
    """Operational pacing heuristic v1: 150 words/minute, bounded to 3–15 seconds."""
    word_count = max(1, len(scene_text.split()))
    estimate = math.ceil(word_count * 60_000 / 150)
    return max(3_000, min(15_000, estimate))


def _scene_lines(scene_title: str, on_screen_text: list[str]) -> list[str]:
    return [line for line in (scene_title, *on_screen_text) if line.strip()]


def render_scene_card(
    scene_title: str,
    on_screen_text: list[str],
    *,
    visual_bytes: bytes | None = None,
) -> tuple[bytes, int, int]:
    width, height = VIDEO_WIDTH, VIDEO_HEIGHT
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    if visual_bytes is not None:
        try:
            visual = fitz.open(stream=visual_bytes)
            image = visual[0].get_pixmap(alpha=False)
            page.insert_image(page.rect, pixmap=image, keep_proportion=False)
        except Exception:
            raise MediaRenderError("invalid_scene_visual") from None
        page.draw_rect(
            fitz.Rect(0, 430, width, height), color=None, fill=(0.05, 0.17, 0.19), fill_opacity=0.88
        )
    else:
        page.draw_rect(page.rect, color=None, fill=(0.09, 0.23, 0.24))
        page.draw_rect(fitz.Rect(0, 0, width, 15), color=None, fill=(0.86, 0.63, 0.28))
    lines = _scene_lines(scene_title, on_screen_text)
    y = 520 if visual_bytes is not None else 250
    for index, line in enumerate(lines):
        max_chars = 37 if index == 0 else 55
        wrapped = _wrap(line, max_chars)
        fontsize = 42 if index == 0 else 29
        for wrapped_line in wrapped:
            page.insert_text(
                fitz.Point(76, y),
                wrapped_line,
                fontsize=fontsize,
                fontname="helv",
                color=(1, 1, 1),
            )
            y += int(fontsize * 1.45)
        if index == 0:
            y += 26
        if y > height - 40:
            raise MediaRenderError("scene_text_exceeds_layout_limit")
    png = page.get_pixmap(alpha=False).tobytes("png")
    return png, width, height


def _run_tool(
    tool: str, args: list[str], *, cwd: Path | None = None, timeout: int
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(tool)
    if executable is None:
        raise MediaRenderError(f"{tool}_unavailable")
    try:
        result = subprocess.run(
            [executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise MediaRenderError(f"{tool}_timeout") from None
    except OSError:
        raise MediaRenderError(f"{tool}_unavailable") from None
    if result.returncode != 0:
        raise MediaRenderError(f"{tool}_failed")
    return result


def ffmpeg_version() -> str:
    result = _run_tool("ffmpeg", ["-version"], timeout=10)
    return result.stdout.splitlines()[0][:120] if result.stdout else "ffmpeg-unknown"


def ffprobe_version() -> str:
    result = _run_tool("ffprobe", ["-version"], timeout=10)
    return result.stdout.splitlines()[0][:120] if result.stdout else "ffprobe-unknown"


def probe_path(path: Path, *, max_duration_ms: int = MAX_VIDEO_DURATION_MS) -> ProbeResult:
    version = ffprobe_version()
    result = _run_tool(
        "ffprobe",
        [
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        format_info = payload["format"]
        duration_ms = round(float(format_info["duration"]) * 1_000)
        video_stream = next((item for item in streams if item["codec_type"] == "video"), None)
        audio_stream = next((item for item in streams if item["codec_type"] == "audio"), None)
        fps: float | None = None
        if video_stream is not None:
            ratio = video_stream.get("avg_frame_rate", "0/1").split("/", 1)
            denominator = float(ratio[1]) if len(ratio) == 2 else 0
            fps = float(ratio[0]) / denominator if denominator else None
        if duration_ms <= 0 or duration_ms > max_duration_ms:
            raise ValueError("duration")
        return ProbeResult(
            width=int(video_stream["width"]) if video_stream else None,
            height=int(video_stream["height"]) if video_stream else None,
            duration_ms=duration_ms,
            fps=fps,
            has_video=video_stream is not None,
            has_audio=audio_stream is not None,
            tool_version=version,
            format_name=str(format_info.get("format_name", "")),
        )
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
        raise MediaRenderError("media_probe_validation_failed") from None


def probe_media_bytes(content: bytes, suffix: str, *, max_duration_ms: int) -> ProbeResult:
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="axiomweave-probe-") as directory:
            path = Path(directory) / f"source.{suffix}"
            path.write_bytes(content)
            return probe_path(path, max_duration_ms=max_duration_ms)
    except OSError:
        raise MediaRenderError("media_probe_input_failed") from None


def compose_mp4(
    output_path: Path,
    scene_paths: list[Path],
    audio_paths: list[Path | None],
    durations_ms: list[int],
    workdir: Path,
) -> tuple[ProbeResult, int]:
    if (
        not scene_paths
        or len(scene_paths) != len(audio_paths)
        or len(scene_paths) != len(durations_ms)
    ):
        raise MediaRenderError("invalid_video_plan")
    if sum(durations_ms) > MAX_VIDEO_DURATION_MS:
        raise MediaRenderError("video_duration_limit_exceeded")
    ffmpeg_tool_version = ffmpeg_version()
    encoded_clips: list[Path] = []
    for index, (scene_path, audio_path, duration_ms) in enumerate(
        zip(scene_paths, audio_paths, durations_ms, strict=True)
    ):
        if duration_ms < 1_000 or duration_ms > MAX_VIDEO_DURATION_MS:
            raise MediaRenderError("invalid_scene_duration")
        clip = workdir / f"clip_{index:03d}.mp4"
        args = [
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            str(VIDEO_FPS),
            "-i",
            str(scene_path),
        ]
        if audio_path is None:
            args.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration_ms / 1000:.3f}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
            )
        else:
            args.extend(["-protocol_whitelist", "file,pipe", "-i", str(audio_path)])
        args.extend(
            [
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-vf",
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={VIDEO_FPS},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(clip),
            ]
        )
        if audio_path is not None:
            audio_index = args.index("-t")
            args[audio_index:audio_index] = ["-af", "apad"]
        _run_tool("ffmpeg", args, cwd=workdir, timeout=FFMPEG_TIMEOUT_SECONDS)
        probe_path(clip)
        encoded_clips.append(clip)
    concat_file = workdir / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{clip.name}'\n" for clip in encoded_clips), encoding="utf-8"
    )
    _run_tool(
        "ffmpeg",
        [
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output_path),
        ],
        cwd=workdir,
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    if output_path.stat().st_size <= 0 or output_path.stat().st_size > MAX_VIDEO_BYTES:
        raise MediaRenderError("video_file_size_invalid")
    probed = probe_path(output_path)
    result = ProbeResult(
        width=probed.width,
        height=probed.height,
        duration_ms=probed.duration_ms,
        fps=probed.fps,
        has_video=probed.has_video,
        has_audio=probed.has_audio,
        tool_version=f"{ffmpeg_tool_version};{probed.tool_version}",
        format_name=probed.format_name,
    )
    if not result.has_video or (result.width, result.height) != (VIDEO_WIDTH, VIDEO_HEIGHT):
        raise MediaRenderError("video_output_validation_failed")
    if result.fps is None or abs(result.fps - VIDEO_FPS) > 0.01:
        raise MediaRenderError("video_fps_validation_failed")
    expected_duration = sum(durations_ms)
    if abs(result.duration_ms - expected_duration) > 1_000:
        raise MediaRenderError("video_duration_validation_failed")
    if not result.has_audio:
        raise MediaRenderError("video_audio_stream_missing")
    return result, len(encoded_clips)


def webvtt_for_plan(plan: dict[str, Any]) -> bytes:
    cues: list[str] = ["WEBVTT", ""]
    cursor = 0
    for index, scene in enumerate(plan["scenes"], 1):
        duration = int(scene["duration_ms"])
        start = _format_time(cursor)
        end = _format_time(cursor + duration)
        text_lines = [scene.get("narration", ""), *scene.get("on_screen_text", [])]
        caption = "\n".join(html.escape(line.strip()) for line in text_lines if line.strip())
        if not caption:
            caption = html.escape(scene["title"])
        cues.extend([str(index), f"{start} --> {end}", caption, ""])
        cursor += duration
    return "\n".join(cues).encode("utf-8")


def _format_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def video_spec_from_content(content: str) -> VideoPackageSpec:
    try:
        return VideoPackageSpec.model_validate_json(content)
    except Exception:
        raise MediaRenderError("artifact_spec_invalid") from None


def infographic_spec_from_content(content: str) -> InfographicSpec:
    try:
        return InfographicSpec.model_validate_json(content)
    except Exception:
        raise MediaRenderError("artifact_spec_invalid") from None


def visual_data_uri(content: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
