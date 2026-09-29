import {
  OUTPUT_TYPES,
  type DashboardItem,
  type GeneratedArtifact,
  type OutputType,
  type PresentationDocument,
  type SavedTransformation,
  type SourceRevisionStatus,
  type TransformationDetail,
  type WorkflowStatus,
} from "./types";

export const SOURCE_TEXT_MAX_LENGTH = 20_000;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function sourceCharacterCount(sourceText: string): number {
  return Array.from(sourceText).length;
}

export function isWorkflowStatus(value: unknown): value is WorkflowStatus {
  return [
    "Draft",
    "Generating",
    "Review Required",
    "Partial Failure",
    "Complete",
  ].includes(String(value));
}

export function isDashboardItem(value: unknown): value is DashboardItem {
  return (
    isRecord(value) &&
    Number.isInteger(value.transformation_run_id) &&
    isRecord(value.source_version) &&
    typeof value.source_version.id === "number" &&
    typeof value.source_version.version_number === "number" &&
    typeof value.source_version.content_hash === "string" &&
    Array.isArray(value.output_types) &&
    Array.isArray(value.artifact_states) &&
    isWorkflowStatus(value.status) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export function isGeneratedArtifact(
  value: unknown,
): value is GeneratedArtifact {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.artifact_run_id) ||
    !OUTPUT_TYPES.some((output) => output.value === value.output_type) ||
    !["pending", "running", "succeeded", "failed"].includes(
      String(value.status),
    )
  ) {
    return false;
  }
  if (value.artifact_version === null) return value.status !== "succeeded";
  if (!isRecord(value.artifact_version)) return false;
  return (
    typeof value.artifact_version.content === "string" &&
    (typeof value.artifact_version.provider === "string" ||
      value.artifact_version.provider === null) &&
    (typeof value.artifact_version.model === "string" ||
      value.artifact_version.model === null) &&
    typeof value.artifact_version.source_version_number === "number" &&
    typeof value.artifact_version.version_number === "number"
  );
}

export function isTransformationDetail(
  value: unknown,
): value is TransformationDetail {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.transformation_run_id) ||
    !isRecord(value.source_version) ||
    !isRecord(value.controls) ||
    !isWorkflowStatus(value.status) ||
    !Array.isArray(value.artifact_runs)
  ) {
    return false;
  }
  return value.artifact_runs.every(
    (item: unknown) =>
      isRecord(item) &&
      Number.isInteger(item.artifact_run_id) &&
      OUTPUT_TYPES.some((output) => output.value === item.output_type) &&
      ["pending", "running", "succeeded", "failed"].includes(
        String(item.status),
      ) &&
      Array.isArray(item.versions) &&
      item.versions.every(
        (version: unknown) =>
          isRecord(version) &&
          Number.isInteger(version.id) &&
          Number.isInteger(version.version_number) &&
          typeof version.content === "string" &&
          typeof version.source_version_number === "number" &&
          ["draft", "accepted", "rejected"].includes(
            String(version.review_status),
          ),
      ),
  );
}

export function isSavedTransformation(
  value: unknown,
): value is SavedTransformation {
  if (
    !isRecord(value) ||
    value.status !== "saved" ||
    !isRecord(value.source_version)
  ) {
    return false;
  }
  const version = value.source_version;
  return (
    Number.isInteger(value.transformation_run_id) &&
    Number.isInteger(value.source_id) &&
    Number.isInteger(version.id) &&
    version.version_number === 1 &&
    typeof version.content_hash === "string" &&
    /^[a-f0-9]{64}$/.test(version.content_hash) &&
    Number.isInteger(version.segment_count) &&
    (version.segment_count as number) >= 0 &&
    Array.isArray(value.output_types) &&
    value.output_types.length > 0 &&
    value.output_types.every((outputType: unknown) =>
      OUTPUT_TYPES.some((option) => option.value === outputType),
    )
  );
}

export function isSourceRevisionStatus(
  value: unknown,
): value is SourceRevisionStatus {
  return (
    isRecord(value) &&
    Number.isInteger(value.transformation_run_id) &&
    isRecord(value.source_version) &&
    Array.isArray(value.changes) &&
    Array.isArray(value.potentially_affected_artifacts)
  );
}

export function isExtractedText(value: unknown): value is {
  filename: string;
  media_type: string;
  character_count: number;
  source_text: string;
  ocr_used: boolean;
} {
  return (
    isRecord(value) &&
    typeof value.filename === "string" &&
    typeof value.media_type === "string" &&
    typeof value.source_text === "string" &&
    typeof value.ocr_used === "boolean" &&
    value.source_text.trim().length > 0 &&
    sourceCharacterCount(value.source_text) <= SOURCE_TEXT_MAX_LENGTH &&
    Number.isInteger(value.character_count) &&
    value.character_count === sourceCharacterCount(value.source_text)
  );
}

export function extractionError(body: unknown, status: number): string {
  if (
    isRecord(body) &&
    isRecord(body.error) &&
    typeof body.error.message === "string"
  ) {
    return body.error.message;
  }
  const detail = isRecord(body) && isRecord(body.detail) ? body.detail : null;
  const code = detail && typeof detail.code === "string" ? detail.code : "";
  const messages: Record<string, string> = {
    unsupported_file: "Choose a TXT, MD, DOCX, or PDF file.",
    unsupported_media_type: "The file type does not match its contents.",
    file_too_large: "This file is too large. Choose a smaller document.",
    too_many_pages: "This PDF has more than the 20-page limit.",
    too_many_ocr_pages: "This PDF has more than the 8-scanned-page OCR limit.",
    encrypted_pdf: "Password-protected PDFs are not supported.",
    no_readable_text: "No readable text was found in this document.",
    ocr_not_configured:
      "This PDF has scanned pages, but scanned page reading is not configured.",
    source_too_long:
      "Extracted text exceeds the 20,000-character source limit.",
    invalid_pdf: "This PDF could not be opened. Check the file and try again.",
    invalid_document:
      "This DOCX file could not be opened. Check the file and try again.",
    invalid_encoding: "The text file must use UTF-8 encoding.",
    empty_source: "The document does not contain any readable text.",
    empty_pdf: "This PDF does not contain any pages.",
    ocr_failed: "Scanned pages could not be read. Please try another PDF.",
  };
  if (messages[code]) return messages[code];
  const message =
    detail && typeof detail.message === "string" ? detail.message : null;
  if (typeof message === "string") return message;
  if (status === 413) {
    return "This file is too large. Choose a text file up to 80 KiB.";
  }
  if (status === 415) {
    return "Choose a .txt or .md file.";
  }
  if (status === 422) {
    return "The file must contain non-empty UTF-8 text within the source limit.";
  }
  return "The file could not be read. Please try again.";
}

const FIELD_LABELS: Record<string, string> = {
  source_text: "Source text",
  output_types: "Outputs",
  audience: "Audience",
  tone: "Tone",
  language: "Language",
  detail_level: "Detail level",
  objective: "Communication objective",
  style: "Content style",
  supporting_context: "Supporting context",
};

export function validationMessage(body: unknown): string {
  if (!isRecord(body) || !isRecord(body.error)) {
    return "Review the fields and try again.";
  }
  const fields = body.error.fields;
  if (!Array.isArray(fields)) return "Review the fields and try again.";
  const labels = fields
    .map((item: unknown) => {
      if (!isRecord(item) || typeof item.field !== "string") return null;
      const field = item.field.split(".")[0];
      return FIELD_LABELS[field] ?? null;
    })
    .filter((label): label is string => label !== null);
  return labels.length
    ? "Please review: " + [...new Set(labels)].join(", ") + "."
    : "Review the fields and try again.";
}

export function outputLabel(outputType: string): string {
  return (
    OUTPUT_TYPES.find((output) => output.value === outputType)?.label ??
    "Artifact"
  );
}

export function deriveTransformationTitle(sourceText: string): string {
  const lines = sourceText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const heading = lines.find((line) => /^#{1,6}\s+/.test(line));
  const candidate = heading
    ? heading.replace(/^#{1,6}\s+/, "")
    : (lines.find((line) => !/^[-*]\s+/.test(line)) ?? "");
  const sentence = candidate.split(/(?<=[.!?])\s+/u)[0] ?? "";
  const cleaned = sentence
    .replace(/[*_~]/g, "")
    .replaceAll(String.fromCharCode(96), "")
    .replace(/^\[([^\]]+)\]\([^)]*\)$/, "$1")
    .trim();
  if (!cleaned) return "Untitled transformation";
  if (cleaned.length <= 68) return cleaned;
  return cleaned.slice(0, 65).trimEnd() + "…";
}

export function relativeDate(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "Recently updated";
  const seconds = Math.round((timestamp - Date.now()) / 1000);
  const absoluteSeconds = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absoluteSeconds < 60) return formatter.format(0, "second");
  if (absoluteSeconds < 3600) {
    return formatter.format(Math.round(seconds / 60), "minute");
  }
  if (absoluteSeconds < 86400) {
    return formatter.format(Math.round(seconds / 3600), "hour");
  }
  if (absoluteSeconds < 2_592_000) {
    return formatter.format(Math.round(seconds / 86400), "day");
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(timestamp);
}

export function transformationStatus(item: DashboardItem): string {
  const statuses = item.artifact_states;
  if (
    item.status === "Partial Failure" ||
    statuses.some((artifact) => artifact.status === "failed")
  ) {
    return "Needs attention";
  }
  if (
    item.status === "Generating" ||
    statuses.some(
      (artifact) =>
        artifact.status === "running" || artifact.status === "pending",
    )
  ) {
    return "Generating";
  }
  if (
    statuses.some(
      (artifact) =>
        artifact.review_status === "draft" ||
        (artifact.status === "succeeded" && artifact.review_status === null),
    )
  ) {
    return "Ready for review";
  }
  if (
    statuses.length > 0 &&
    statuses.every((artifact) => artifact.review_status === "accepted")
  ) {
    return "Accepted";
  }
  if (statuses.some((artifact) => artifact.review_status === "rejected")) {
    return "Rejected";
  }
  if (item.status === "Complete") return "Complete";
  return "Draft";
}

export function artifactStatus(
  status: string | null,
  reviewStatus: string | null,
): string {
  if (reviewStatus === "accepted") return "Accepted";
  if (reviewStatus === "rejected") return "Rejected";
  if (status === "failed") return "Needs attention";
  if (status === "running") return "Generating";
  if (status === "pending") return "Waiting";
  if (status === "succeeded") return "Ready";
  return "Not selected";
}

export function parsePresentation(
  content: string,
): PresentationDocument | null {
  try {
    const value: unknown = JSON.parse(content);
    if (
      !isRecord(value) ||
      typeof value.title !== "string" ||
      !Array.isArray(value.slides)
    ) {
      return null;
    }
    const slides = value.slides.filter(
      (slide): slide is Record<string, unknown> =>
        isRecord(slide) &&
        typeof slide.title === "string" &&
        typeof slide.key_message === "string" &&
        Array.isArray(slide.bullets) &&
        slide.bullets.every((bullet: unknown) => typeof bullet === "string") &&
        typeof slide.visual_recommendation === "string" &&
        typeof slide.speaker_notes === "string",
    );
    if (slides.length !== value.slides.length || slides.length === 0)
      return null;
    return {
      title: value.title,
      slides: slides.map((slide) => ({
        title: slide.title as string,
        key_message: slide.key_message as string,
        bullets: slide.bullets as string[],
        visual_recommendation: slide.visual_recommendation as string,
        speaker_notes: slide.speaker_notes as string,
      })),
    };
  } catch {
    return null;
  }
}

export function artifactExportText(
  outputType: OutputType,
  content: string,
): string {
  if (outputType !== "presentation") return content;
  const presentation = parsePresentation(content);
  if (!presentation) return content;
  return [
    "# " + presentation.title,
    ...presentation.slides.flatMap((slide, index) => [
      "# Slide " + (index + 1) + " — " + slide.title,
      "",
      "**Key message**",
      "",
      slide.key_message,
      "",
      ...slide.bullets.map((bullet) => "- " + bullet),
      "",
      "**Visual recommendation**",
      "",
      slide.visual_recommendation,
      "",
      "**Speaker notes**",
      "",
      slide.speaker_notes,
    ]),
  ].join("\n");
}

export function orderedVersionIds<
  T extends { id: number; version_number: number },
>(versions: T[]): number[] {
  return [...versions]
    .sort((left, right) => left.version_number - right.version_number)
    .map((version) => version.id);
}
