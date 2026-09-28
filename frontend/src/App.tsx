import { useEffect, useRef, useState, type FormEvent } from "react";

const OUTPUT_TYPES = [
  { value: "executive_summary", label: "Executive Summary" },
  { value: "linkedin_post", label: "Professional / LinkedIn Post" },
  { value: "advisory", label: "Formal Advisory" },
  { value: "presentation", label: "Presentation + Speaker Notes" },
] as const;

type OutputType = (typeof OUTPUT_TYPES)[number]["value"];
type DetailLevel = "brief" | "standard" | "detailed";

type TransformationRequest = {
  source_text: string;
  output_types: OutputType[];
  audience: string;
  tone: string;
  language: string;
  detail_level: DetailLevel;
  objective: string;
  style: string;
  supporting_context: string;
};

type SavedTransformation = {
  status: "saved";
  transformation_run_id: number;
  source_id: number;
  source_version: {
    id: number;
    version_number: 1;
    content_hash: string;
    segment_count: number;
  };
  output_types: OutputType[];
};

type ArtifactRunStatus = "pending" | "running" | "succeeded" | "failed";

type GeneratedArtifactVersion = {
  id: number;
  version_number: number;
  source_version_id: number;
  source_version_number: number;
  content: string;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  prompt_hash: string | null;
};

type GeneratedArtifact = {
  artifact_run_id: number;
  output_type: OutputType;
  status: ArtifactRunStatus;
  artifact_version: GeneratedArtifactVersion | null;
};

type WorkflowStatus =
  "Draft" | "Generating" | "Review Required" | "Partial Failure" | "Complete";

type DashboardItem = {
  transformation_run_id: number;
  source_version: {
    id: number;
    version_number: number;
    content_hash: string;
    created_at: string;
  };
  output_types: string[];
  artifact_states: {
    output_type: OutputType;
    status: ArtifactRunStatus | null;
    latest_version_number: number | null;
    review_status: "draft" | "accepted" | "rejected" | null;
  }[];
  status: WorkflowStatus;
  created_at: string;
  updated_at: string;
};

type ReviewArtifactVersion = GeneratedArtifactVersion & {
  review_status: "draft" | "accepted" | "rejected";
  created_at: string;
};

type ReviewArtifactRun = {
  artifact_run_id: number;
  output_type: OutputType;
  status: ArtifactRunStatus;
  versions: ReviewArtifactVersion[];
};

type TransformationDetail = {
  transformation_run_id: number;
  source_version: DashboardItem["source_version"];
  controls: Record<string, string>;
  output_types: string[];
  status: WorkflowStatus;
  created_at: string;
  updated_at: string;
  artifact_runs: ReviewArtifactRun[];
};

type WorkspaceScreen = "dashboard" | "new" | "review";

type HealthState = "loading" | "online" | "offline";
type SourceMode = "paste" | "upload";

type SourceFileMetadata = {
  filename: string;
  character_count: number;
};

const SOURCE_TEXT_MAX_LENGTH = 20_000;

function sourceCharacterCount(sourceText: string): number {
  return Array.from(sourceText).length;
}

const INITIAL_REQUEST: TransformationRequest = {
  source_text: "",
  output_types: [],
  audience: "General public",
  tone: "Clear and informative",
  language: "English",
  detail_level: "standard",
  objective: "Inform the audience",
  style: "Plain language",
  supporting_context: "",
};

const FIELD_LABELS: Record<string, string> = {
  source_text: "Source text",
  output_types: "Output types",
  audience: "Audience",
  tone: "Tone",
  language: "Language",
  detail_level: "Detail level",
  objective: "Communication objective",
  style: "Content style",
  supporting_context: "Supporting context",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isGeneratedArtifact(value: unknown): value is GeneratedArtifact {
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

function isWorkflowStatus(value: unknown): value is WorkflowStatus {
  return [
    "Draft",
    "Generating",
    "Review Required",
    "Partial Failure",
    "Complete",
  ].includes(String(value));
}

function isDashboardItem(value: unknown): value is DashboardItem {
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

function isTransformationDetail(value: unknown): value is TransformationDetail {
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
  return value.artifact_runs.every((item: unknown) => {
    if (
      !isRecord(item) ||
      !Number.isInteger(item.artifact_run_id) ||
      !OUTPUT_TYPES.some((output) => output.value === item.output_type) ||
      !["pending", "running", "succeeded", "failed"].includes(
        String(item.status),
      ) ||
      !Array.isArray(item.versions)
    ) {
      return false;
    }
    return item.versions.every(
      (version: unknown) =>
        isRecord(version) &&
        Number.isInteger(version.id) &&
        Number.isInteger(version.version_number) &&
        typeof version.content === "string" &&
        typeof version.source_version_number === "number" &&
        ["draft", "accepted", "rejected"].includes(
          String(version.review_status),
        ),
    );
  });
}

function PresentationArtifact({ content }: { content: string }) {
  let value: unknown;
  try {
    value = JSON.parse(content);
  } catch {
    return <p>Presentation content could not be displayed.</p>;
  }
  if (
    !isRecord(value) ||
    typeof value.title !== "string" ||
    !Array.isArray(value.slides)
  ) {
    return <p>Presentation content could not be displayed.</p>;
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
  if (slides.length !== value.slides.length) {
    return <p>Presentation content could not be displayed.</p>;
  }
  return (
    <div>
      <h3>{value.title}</h3>
      {slides.map((slide, index) => (
        <article className="presentation-slide" key={`${index}-${slide.title}`}>
          <h4>
            Slide {index + 1}: {slide.title as string}
          </h4>
          <p>{slide.key_message as string}</p>
          <ul>
            {(slide.bullets as string[]).map((bullet, bulletIndex) => (
              <li key={`${bulletIndex}-${bullet}`}>{bullet}</li>
            ))}
          </ul>
          <p>
            <strong>Visual recommendation:</strong>{" "}
            {slide.visual_recommendation as string}
          </p>
          <p>
            <strong>Speaker notes:</strong> {slide.speaker_notes as string}
          </p>
        </article>
      ))}
    </div>
  );
}

function isSavedTransformation(value: unknown): value is SavedTransformation {
  if (
    !isRecord(value) ||
    value.status !== "saved" ||
    !isRecord(value.source_version)
  )
    return false;
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

function isExtractedText(value: unknown): value is {
  filename: string;
  media_type: "text/plain" | "text/markdown";
  character_count: number;
  source_text: string;
} {
  return (
    isRecord(value) &&
    typeof value.filename === "string" &&
    (value.media_type === "text/plain" ||
      value.media_type === "text/markdown") &&
    typeof value.source_text === "string" &&
    value.source_text.trim().length > 0 &&
    sourceCharacterCount(value.source_text) <= SOURCE_TEXT_MAX_LENGTH &&
    Number.isInteger(value.character_count) &&
    value.character_count === sourceCharacterCount(value.source_text)
  );
}

function extractionError(body: unknown, status: number): string {
  const message =
    isRecord(body) && isRecord(body.error) ? body.error.message : null;
  if (typeof message === "string") return message;
  if (status === 413)
    return "The file is too large. Choose a file up to 80 KiB.";
  if (status === 415)
    return "Unsupported file. Choose a .txt or .md text file.";
  if (status === 422)
    return "The file must contain non-empty UTF-8 text within the source limit.";
  return "The file could not be extracted. Please try again.";
}

function validationMessage(body: unknown): string {
  if (!isRecord(body) || !isRecord(body.error)) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  const fields = body.error.fields;
  if (!Array.isArray(fields)) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  const labels = fields
    .map((item: unknown) => {
      if (!isRecord(item) || typeof item.field !== "string") return null;
      const field = item.field.split(".")[0];
      return FIELD_LABELS[field] ?? null;
    })
    .filter((label): label is string => label !== null);

  if (labels.length === 0) {
    return "The request did not pass backend validation. Review the fields and try again.";
  }

  return `Please review: ${[...new Set(labels)].join(", ")}.`;
}

function Workspace({ onLogout }: { onLogout: () => Promise<boolean> }) {
  const [screen, setScreen] = useState<WorkspaceScreen>("dashboard");
  const [health, setHealth] = useState<HealthState>("loading");
  const [request, setRequest] =
    useState<TransformationRequest>(INITIAL_REQUEST);
  const [sourceMode, setSourceMode] = useState<SourceMode>("paste");
  const [sourceFile, setSourceFile] = useState<SourceFileMetadata | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedTransformation | null>(null);
  const [generatedArtifacts, setGeneratedArtifacts] = useState<
    GeneratedArtifact[]
  >([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [dashboardItems, setDashboardItems] = useState<DashboardItem[]>([]);
  const [isDashboardLoading, setIsDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [reviewDetail, setReviewDetail] = useState<TransformationDetail | null>(
    null,
  );
  const [isReviewLoading, setIsReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [selectedVersions, setSelectedVersions] = useState<
    Record<number, number>
  >({});
  const [editingArtifactRunId, setEditingArtifactRunId] = useState<
    number | null
  >(null);
  const [editContent, setEditContent] = useState("");
  const [isReviewActionRunning, setIsReviewActionRunning] = useState(false);
  const [logoutError, setLogoutError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Health check failed");
        const body: unknown = await response.json();
        if (!isRecord(body) || body.status !== "ok") {
          throw new Error("Invalid health response");
        }
        setHealth("online");
      } catch {
        if (!controller.signal.aborted) setHealth("offline");
      }
    }

    void checkHealth();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (screen !== "dashboard") return;
    const controller = new AbortController();
    setIsDashboardLoading(true);
    setDashboardError(null);
    async function loadDashboard() {
      try {
        const response = await fetch("/api/transformations", {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("dashboard unavailable");
        const body: unknown = await response.json();
        if (!Array.isArray(body) || !body.every(isDashboardItem)) {
          throw new Error("unexpected dashboard response");
        }
        setDashboardItems(body);
      } catch {
        if (!controller.signal.aborted) {
          setDashboardError(
            "Could not load your transformations. Please retry.",
          );
        }
      } finally {
        if (!controller.signal.aborted) setIsDashboardLoading(false);
      }
    }
    void loadDashboard();
    return () => controller.abort();
  }, [screen]);

  async function openReviewWorkspace(transformationRunId: number) {
    setIsReviewLoading(true);
    setReviewError(null);
    try {
      const response = await fetch(
        `/api/transformations/${transformationRunId}`,
        { credentials: "include" },
      );
      if (!response.ok) throw new Error("review unavailable");
      const body: unknown = await response.json();
      if (!isTransformationDetail(body)) {
        throw new Error("unexpected review response");
      }
      setReviewDetail(body);
      setSelectedVersions({});
      setEditingArtifactRunId(null);
      setScreen("review");
    } catch {
      setReviewError("Could not open this review workspace. Please retry.");
    } finally {
      setIsReviewLoading(false);
    }
  }

  async function refreshReview() {
    if (reviewDetail) {
      await openReviewWorkspace(reviewDetail.transformation_run_id);
    }
  }

  function updateRequest<K extends keyof TransformationRequest>(
    field: K,
    value: TransformationRequest[K],
  ) {
    setRequest((current) => ({ ...current, [field]: value }));
    setError(null);
    setSaved(null);
    setGeneratedArtifacts([]);
    setGenerationError(null);
  }

  function toggleOutput(outputType: OutputType, checked: boolean) {
    const outputTypes = checked
      ? [...request.output_types, outputType]
      : request.output_types.filter((item) => item !== outputType);
    updateRequest("output_types", outputTypes);
  }

  function switchSourceMode(mode: SourceMode) {
    setSourceMode(mode);
    setRequest((current) => ({ ...current, source_text: "" }));
    setSourceFile(null);
    setError(null);
    setSaved(null);
    setGeneratedArtifacts([]);
    setGenerationError(null);
  }

  async function extractSourceFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setSaved(null);
    setGeneratedArtifacts([]);
    setGenerationError(null);
    setSourceFile(null);
    setRequest((current) => ({ ...current, source_text: "" }));
    setIsExtracting(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/sources/text-file", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        setError("The backend returned an unreadable extraction response.");
        return;
      }

      if (!response.ok) {
        setError(extractionError(body, response.status));
        return;
      }

      if (!isExtractedText(body)) {
        setError(
          "The backend returned an unexpected file extraction response.",
        );
        return;
      }

      setRequest((current) => ({ ...current, source_text: body.source_text }));
      setSourceFile({
        filename: body.filename,
        character_count: body.character_count,
      });
    } catch {
      setError(
        "Could not reach the backend to extract this file. Check the connection and try again.",
      );
    } finally {
      setIsExtracting(false);
    }
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(null);

    if (!request.source_text.trim()) {
      setError("Enter source text before saving the transformation.");
      return;
    }

    if (request.output_types.length === 0) {
      setError("Choose at least one output type.");
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      const response = await fetch("/api/transformations", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      let body: unknown;
      try {
        body = await response.json();
      } catch {
        setError(
          "The backend returned an unreadable save response. Please retry.",
        );
        return;
      }

      if (response.status === 422) {
        setError(validationMessage(body));
        return;
      }

      if (!response.ok) {
        setError("The transformation could not be saved. Please retry.");
        return;
      }

      if (!isSavedTransformation(body)) {
        setError(
          "The backend returned an unexpected save response. Please retry.",
        );
        return;
      }

      setSaved(body);
    } catch {
      setError(
        "Could not reach the backend to save. Check the connection and try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function generateSelectedArtifacts() {
    if (!saved) return;
    setGenerationError(null);
    setIsGenerating(true);
    try {
      const response = await fetch(
        `/api/transformations/${saved.transformation_run_id}/generate`,
        { method: "POST", credentials: "include" },
      );
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        setGenerationError(
          "The backend returned an unreadable generation response.",
        );
        return;
      }
      if (!response.ok) {
        const code =
          isRecord(body) && isRecord(body.error) ? body.error.code : null;
        setGenerationError(
          code === "generation_not_configured"
            ? "Generation is not configured on this server."
            : "The selected outputs could not be generated. Please retry.",
        );
        return;
      }
      if (
        !isRecord(body) ||
        !["succeeded", "partial_failure", "running"].includes(
          String(body.status),
        ) ||
        !Array.isArray(body.artifacts) ||
        !body.artifacts.every(isGeneratedArtifact)
      ) {
        setGenerationError(
          "The backend returned an unexpected generation response.",
        );
        return;
      }
      setGeneratedArtifacts(body.artifacts);
    } catch {
      setGenerationError(
        "Could not reach the backend to generate the selected outputs.",
      );
    } finally {
      setIsGenerating(false);
    }
  }

  async function retryArtifact(artifactRunId: number) {
    setGenerationError(null);
    try {
      const response = await fetch(
        `/api/artifact-runs/${artifactRunId}/retry`,
        {
          method: "POST",
          credentials: "include",
        },
      );
      const body: unknown = await response.json();
      if (!response.ok || !isGeneratedArtifact(body)) {
        setGenerationError(
          "The failed output could not be retried. Please try again.",
        );
        return;
      }
      setGeneratedArtifacts((current) =>
        current.map((artifact) =>
          artifact.artifact_run_id === artifactRunId ? body : artifact,
        ),
      );
    } catch {
      setGenerationError(
        "Could not reach the backend to retry the failed output.",
      );
    }
  }

  async function saveArtifactVersion(artifactRunId: number) {
    setReviewError(null);
    setIsReviewActionRunning(true);
    try {
      const response = await fetch(
        `/api/artifact-runs/${artifactRunId}/versions`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: editContent }),
        },
      );
      if (!response.ok) {
        setReviewError(
          "The artifact version could not be saved. Check its content and retry.",
        );
        return;
      }
      setEditingArtifactRunId(null);
      setEditContent("");
      await refreshReview();
    } catch {
      setReviewError(
        "Could not reach the backend to save this artifact version.",
      );
    } finally {
      setIsReviewActionRunning(false);
    }
  }

  async function regenerateReviewArtifact(artifactRunId: number) {
    setReviewError(null);
    setIsReviewActionRunning(true);
    try {
      const response = await fetch(
        `/api/artifact-runs/${artifactRunId}/regenerate`,
        { method: "POST", credentials: "include" },
      );
      if (!response.ok) {
        setReviewError("The artifact could not be regenerated. Please retry.");
        return;
      }
      await refreshReview();
    } catch {
      setReviewError(
        "Could not reach the backend to regenerate this artifact.",
      );
    } finally {
      setIsReviewActionRunning(false);
    }
  }

  async function retryReviewArtifact(artifactRunId: number) {
    setReviewError(null);
    setIsReviewActionRunning(true);
    try {
      const response = await fetch(
        `/api/artifact-runs/${artifactRunId}/retry`,
        {
          method: "POST",
          credentials: "include",
        },
      );
      if (!response.ok) {
        setReviewError("The failed output could not be retried. Please retry.");
        return;
      }
      await refreshReview();
    } catch {
      setReviewError("Could not reach the backend to retry this output.");
    } finally {
      setIsReviewActionRunning(false);
    }
  }

  async function updateReviewStatus(
    artifactVersionId: number,
    reviewStatus: "accepted" | "rejected",
  ) {
    setReviewError(null);
    setIsReviewActionRunning(true);
    try {
      const response = await fetch(
        `/api/artifact-versions/${artifactVersionId}/review`,
        {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ review_status: reviewStatus }),
        },
      );
      if (!response.ok) {
        setReviewError("The review status could not be updated. Please retry.");
        return;
      }
      await refreshReview();
    } catch {
      setReviewError("Could not reach the backend to update review status.");
    } finally {
      setIsReviewActionRunning(false);
    }
  }

  async function handleLogout() {
    setLogoutError(false);
    if (!(await onLogout())) setLogoutError(true);
  }

  const healthText = {
    loading: "Checking backend",
    online: "Backend connected",
    offline: "Backend unavailable",
  }[health];

  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">AXIOMWEAVE</p>
          <p className="eyebrow">Smart India Hackathon 2026 · NTRO</p>
          <h1>
            {screen === "dashboard"
              ? "Transformations Dashboard"
              : screen === "review"
                ? "Review Workspace"
                : "Content transformation"}
          </h1>
          <p className="intro">
            {screen === "dashboard"
              ? "View saved transformations and open their review history."
              : screen === "review"
                ? "Inspect artifact versions, provenance, and review decisions."
                : "Prepare one source and choose the communication materials you need."}
          </p>
        </div>
        <div className="workspace-header-actions">
          {screen !== "dashboard" && (
            <button
              type="button"
              className="button-secondary"
              onClick={() => setScreen("dashboard")}
            >
              Transformations
            </button>
          )}
          {screen !== "new" && (
            <button
              type="button"
              onClick={() => {
                setSaved(null);
                setGeneratedArtifacts([]);
                setScreen("new");
              }}
            >
              New transformation
            </button>
          )}
          <div className={`health health--${health}`} aria-live="polite">
            <span className="health-dot" aria-hidden="true" />
            {healthText}
          </div>
          <button
            type="button"
            className="button-secondary"
            onClick={() => void handleLogout()}
          >
            Sign out
          </button>
        </div>
      </header>
      {logoutError && (
        <p className="form-message form-message--error" role="alert">
          Sign out could not be completed. Please try again.
        </p>
      )}

      {screen === "dashboard" && (
        <section className="dashboard-panel" aria-label="Saved transformations">
          {dashboardError && (
            <p className="form-message form-message--error" role="alert">
              {dashboardError}
            </p>
          )}
          {isDashboardLoading ? (
            <p role="status">Loading transformations…</p>
          ) : dashboardItems.length === 0 ? (
            <p>
              No transformations yet. Create one to start generating artifacts.
            </p>
          ) : (
            <div className="dashboard-list">
              {dashboardItems.map((item) => (
                <article
                  className="dashboard-card"
                  key={item.transformation_run_id}
                >
                  <div>
                    <h2>Transformation {item.transformation_run_id}</h2>
                    <p>
                      Source V{item.source_version.version_number} ·{" "}
                      {item.output_types.length} selected outputs
                    </p>
                    <ul className="dashboard-output-states">
                      {item.artifact_states.map((artifact) => (
                        <li key={artifact.output_type}>
                          {OUTPUT_TYPES.find(
                            (output) => output.value === artifact.output_type,
                          )?.label ?? artifact.output_type}
                          {artifact.status
                            ? ` · ${artifact.status}`
                            : " · Not generated"}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="dashboard-card-actions">
                    <span
                      className={`workflow-status workflow-status--${item.status.toLowerCase().replaceAll(" ", "-")}`}
                    >
                      {item.status}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        void openReviewWorkspace(item.transformation_run_id)
                      }
                      disabled={isReviewLoading}
                    >
                      Open review
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
          {isReviewLoading && <p role="status">Opening review workspace…</p>}
          {reviewError && (
            <p className="form-message form-message--error" role="alert">
              {reviewError}
            </p>
          )}
        </section>
      )}

      {screen === "review" && reviewDetail && (
        <section
          className="review-workspace"
          aria-label="Artifact review workspace"
        >
          <div className="review-source-summary">
            <div>
              <p className="eyebrow">
                Transformation {reviewDetail.transformation_run_id}
              </p>
              <h2>Source V{reviewDetail.source_version.version_number}</h2>
              <p>SHA-256 {reviewDetail.source_version.content_hash}</p>
            </div>
            <span className="workflow-status">{reviewDetail.status}</span>
          </div>
          <section
            className="review-controls"
            aria-labelledby="review-controls-heading"
          >
            <h3 id="review-controls-heading">Transformation controls</h3>
            <dl>
              {Object.entries(reviewDetail.controls).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
          {reviewError && (
            <p className="form-message form-message--error" role="alert">
              {reviewError}
            </p>
          )}
          {reviewDetail.artifact_runs.length === 0 ? (
            <p>No artifacts have been generated for this transformation yet.</p>
          ) : (
            <div className="review-artifacts">
              {reviewDetail.artifact_runs.map((artifactRun) => {
                const label =
                  OUTPUT_TYPES.find(
                    (output) => output.value === artifactRun.output_type,
                  )?.label ?? artifactRun.output_type;
                const latest = artifactRun.versions.at(-1);
                const selectedVersion =
                  artifactRun.versions.find(
                    (version) =>
                      version.id ===
                      selectedVersions[artifactRun.artifact_run_id],
                  ) ?? latest;
                const isLatest = selectedVersion?.id === latest?.id;
                return (
                  <article
                    className="review-artifact"
                    key={artifactRun.artifact_run_id}
                  >
                    <header>
                      <div>
                        <h3>{label}</h3>
                        <p role="status">{artifactRun.status}</p>
                      </div>
                      {artifactRun.status === "failed" && (
                        <button
                          type="button"
                          onClick={() =>
                            void retryReviewArtifact(
                              artifactRun.artifact_run_id,
                            )
                          }
                          disabled={isReviewActionRunning}
                        >
                          Retry {label}
                        </button>
                      )}
                    </header>
                    {artifactRun.versions.length > 0 ? (
                      <>
                        <nav
                          className="version-history"
                          aria-label={`${label} version history`}
                        >
                          <strong>Versions</strong>
                          {artifactRun.versions.map((version) => (
                            <button
                              type="button"
                              className={
                                version.id === selectedVersion?.id
                                  ? "is-selected"
                                  : ""
                              }
                              key={version.id}
                              onClick={() =>
                                setSelectedVersions((current) => ({
                                  ...current,
                                  [artifactRun.artifact_run_id]: version.id,
                                }))
                              }
                            >
                              V{version.version_number} ·{" "}
                              {version.review_status}
                            </button>
                          ))}
                        </nav>
                        {selectedVersion && (
                          <>
                            <section
                              className="artifact-provenance"
                              aria-label="Artifact provenance"
                            >
                              <strong>
                                Source V{selectedVersion.source_version_number}
                              </strong>
                              <span>
                                {selectedVersion.provider &&
                                selectedVersion.model
                                  ? `${selectedVersion.provider} / ${selectedVersion.model}`
                                  : "Manually edited"}
                              </span>
                              {selectedVersion.prompt_version && (
                                <span>
                                  Prompt V{selectedVersion.prompt_version} ·{" "}
                                  {selectedVersion.prompt_hash}
                                </span>
                              )}
                            </section>
                            {editingArtifactRunId ===
                              artifactRun.artifact_run_id && isLatest ? (
                              <div className="artifact-editor">
                                <label
                                  htmlFor={`artifact-editor-${artifactRun.artifact_run_id}`}
                                >
                                  Edit {label}
                                </label>
                                <textarea
                                  id={`artifact-editor-${artifactRun.artifact_run_id}`}
                                  rows={12}
                                  value={editContent}
                                  onChange={(event) =>
                                    setEditContent(event.target.value)
                                  }
                                />
                                <button
                                  type="button"
                                  disabled={isReviewActionRunning}
                                  onClick={() =>
                                    void saveArtifactVersion(
                                      artifactRun.artifact_run_id,
                                    )
                                  }
                                >
                                  Save new version
                                </button>
                                <button
                                  type="button"
                                  className="button-secondary"
                                  onClick={() => setEditingArtifactRunId(null)}
                                >
                                  Cancel edit
                                </button>
                              </div>
                            ) : artifactRun.output_type === "presentation" ? (
                              <PresentationArtifact
                                content={selectedVersion.content}
                              />
                            ) : (
                              <pre className="review-artifact-content">
                                {selectedVersion.content}
                              </pre>
                            )}
                            {isLatest &&
                              editingArtifactRunId !==
                                artifactRun.artifact_run_id && (
                                <div className="review-actions">
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setEditingArtifactRunId(
                                        artifactRun.artifact_run_id,
                                      );
                                      setEditContent(selectedVersion.content);
                                    }}
                                  >
                                    Edit
                                  </button>
                                  <button
                                    type="button"
                                    className="button-secondary"
                                    disabled={isReviewActionRunning}
                                    onClick={() =>
                                      void regenerateReviewArtifact(
                                        artifactRun.artifact_run_id,
                                      )
                                    }
                                  >
                                    Regenerate
                                  </button>
                                  <button
                                    type="button"
                                    className="button-secondary"
                                    disabled={isReviewActionRunning}
                                    onClick={() =>
                                      void updateReviewStatus(
                                        selectedVersion.id,
                                        "accepted",
                                      )
                                    }
                                  >
                                    Accept
                                  </button>
                                  <button
                                    type="button"
                                    className="button-secondary"
                                    disabled={isReviewActionRunning}
                                    onClick={() =>
                                      void updateReviewStatus(
                                        selectedVersion.id,
                                        "rejected",
                                      )
                                    }
                                  >
                                    Reject
                                  </button>
                                </div>
                              )}
                          </>
                        )}
                      </>
                    ) : (
                      <p>No artifact version is available yet.</p>
                    )}
                  </article>
                );
              })}
            </div>
          )}
          <p className="review-state-note">
            Accepting or rejecting records a workflow decision. It does not
            certify factual accuracy.
          </p>
        </section>
      )}

      {screen === "new" && (
        <form className="request-form" onSubmit={submitRequest} noValidate>
          <section
            className="form-section source-section"
            aria-labelledby="source-heading"
          >
            <div className="section-heading">
              <span className="step-number" aria-hidden="true">
                1
              </span>
              <div>
                <h2 id="source-heading">Source content</h2>
                <p>Paste text or upload a lightweight text document.</p>
              </div>
            </div>
            <fieldset className="source-modes">
              <legend className="visually-hidden">Source mode</legend>
              <label>
                <input
                  type="radio"
                  name="source_mode"
                  value="paste"
                  checked={sourceMode === "paste"}
                  disabled={isExtracting}
                  onChange={() => switchSourceMode("paste")}
                />
                Paste text
              </label>
              <label>
                <input
                  type="radio"
                  name="source_mode"
                  value="upload"
                  checked={sourceMode === "upload"}
                  disabled={isExtracting}
                  onChange={() => switchSourceMode("upload")}
                />
                Upload text file
              </label>
            </fieldset>
            {sourceMode === "paste" ? (
              <>
                <label htmlFor="source-text">Text source</label>
                <textarea
                  id="source-text"
                  rows={8}
                  value={request.source_text}
                  onChange={(event) => {
                    setSourceFile(null);
                    updateRequest("source_text", event.target.value);
                  }}
                  placeholder="Paste or write your source text here"
                />
              </>
            ) : (
              <div className="upload-source">
                <label htmlFor="source-file">Text file (.txt or .md)</label>
                <input
                  id="source-file"
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  onChange={(event) =>
                    void extractSourceFile(event.target.files?.[0])
                  }
                  disabled={isExtracting}
                />
                <p className="field-hint">
                  UTF-8 text only. Maximum file size: 80 KiB.
                </p>
                {isExtracting && <p role="status">Extracting text file…</p>}
                {sourceFile && (
                  <p className="field-hint" role="status">
                    {sourceFile.filename} ·{" "}
                    {sourceFile.character_count.toLocaleString()} characters
                  </p>
                )}
              </div>
            )}
            <p className="field-hint">
              Text only. Source content is stored as a versioned source when you
              save.
            </p>
          </section>

          <section className="form-section" aria-labelledby="context-heading">
            <div className="section-heading">
              <span className="step-number" aria-hidden="true">
                2
              </span>
              <div>
                <h2 id="context-heading">Supporting context</h2>
                <p>Optional guidance for the requested transformation.</p>
              </div>
            </div>
            <label htmlFor="supporting-context">
              Supporting context (optional)
            </label>
            <textarea
              id="supporting-context"
              rows={4}
              maxLength={5000}
              value={request.supporting_context}
              onChange={(event) =>
                updateRequest("supporting_context", event.target.value)
              }
              placeholder="Add audience-specific or operational guidance"
            />
            <p className="field-hint">
              Context can guide the transformation but is not treated as source
              evidence.
            </p>
          </section>

          <section className="form-section" aria-labelledby="outputs-heading">
            <div className="section-heading">
              <span className="step-number" aria-hidden="true">
                3
              </span>
              <div>
                <h2 id="outputs-heading">Requested materials</h2>
                <p>Select one or more. All use the same source and settings.</p>
              </div>
            </div>
            <fieldset className="output-options">
              <legend className="visually-hidden">Output types</legend>
              {OUTPUT_TYPES.map((output) => (
                <label className="output-option" key={output.value}>
                  <input
                    type="checkbox"
                    name="output_types"
                    value={output.value}
                    checked={request.output_types.includes(output.value)}
                    onChange={(event) =>
                      toggleOutput(output.value, event.target.checked)
                    }
                  />
                  <span>{output.label}</span>
                </label>
              ))}
            </fieldset>
          </section>

          <section
            className="form-section settings-section"
            aria-labelledby="settings-heading"
          >
            <div className="section-heading">
              <span className="step-number" aria-hidden="true">
                4
              </span>
              <div>
                <h2 id="settings-heading">Communication settings</h2>
                <p>Describe who this is for and how it should communicate.</p>
              </div>
            </div>
            <div className="settings-grid">
              <div className="field">
                <label htmlFor="audience">Audience</label>
                <input
                  id="audience"
                  value={request.audience}
                  onChange={(event) =>
                    updateRequest("audience", event.target.value)
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="tone">Tone</label>
                <input
                  id="tone"
                  value={request.tone}
                  onChange={(event) =>
                    updateRequest("tone", event.target.value)
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="language">Language</label>
                <input
                  id="language"
                  value={request.language}
                  onChange={(event) =>
                    updateRequest("language", event.target.value)
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="detail-level">Detail level</label>
                <select
                  id="detail-level"
                  value={request.detail_level}
                  onChange={(event) =>
                    updateRequest(
                      "detail_level",
                      event.target.value as DetailLevel,
                    )
                  }
                >
                  <option value="brief">Brief</option>
                  <option value="standard">Standard</option>
                  <option value="detailed">Detailed</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="objective">Communication objective</label>
                <input
                  id="objective"
                  value={request.objective}
                  onChange={(event) =>
                    updateRequest("objective", event.target.value)
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="style">Content style</label>
                <input
                  id="style"
                  value={request.style}
                  onChange={(event) =>
                    updateRequest("style", event.target.value)
                  }
                />
              </div>
            </div>
          </section>

          <div className="submit-row">
            <p className="generation-note">
              Save your source and transformation brief. Saving does not
              generate content.
            </p>
            <button type="submit" disabled={isSubmitting || isExtracting}>
              {isSubmitting ? "Saving…" : "Save transformation"}
            </button>
          </div>

          {error && (
            <p className="form-message form-message--error" role="alert">
              {error}
            </p>
          )}
          {saved && (
            <div className="saved-transformation" aria-live="polite">
              <div className="form-message form-message--success" role="status">
                <strong>Transformation saved</strong>
                <span>
                  Source V{saved.source_version.version_number} stored for{" "}
                  {saved.output_types.length} requested{" "}
                  {saved.output_types.length === 1 ? "output" : "outputs"}.
                </span>
              </div>
              {saved.output_types.length > 0 && (
                <button
                  type="button"
                  onClick={generateSelectedArtifacts}
                  disabled={isGenerating || generatedArtifacts.length > 0}
                >
                  {isGenerating
                    ? "Generating selected outputs…"
                    : "Generate selected outputs"}
                </button>
              )}
              {generationError && (
                <p className="form-message form-message--error" role="alert">
                  {generationError}
                </p>
              )}
              {generatedArtifacts.length > 0 && (
                <section aria-labelledby="generated-artifacts-heading">
                  <h2 id="generated-artifacts-heading">Generated outputs</h2>
                  {generatedArtifacts.map((artifact) => {
                    const label =
                      OUTPUT_TYPES.find(
                        (output) => output.value === artifact.output_type,
                      )?.label ?? artifact.output_type;
                    return (
                      <article
                        className="generated-artifact"
                        key={artifact.artifact_run_id}
                      >
                        <h3>{label}</h3>
                        <p role="status">
                          {artifact.status === "succeeded"
                            ? "Succeeded"
                            : artifact.status === "failed"
                              ? "Failed"
                              : artifact.status === "running"
                                ? "Generating"
                                : "Pending"}
                        </p>
                        {artifact.artifact_version && (
                          <>
                            <p>
                              Source V
                              {artifact.artifact_version.source_version_number}{" "}
                              · {artifact.artifact_version.provider} /{" "}
                              {artifact.artifact_version.model}
                            </p>
                            {artifact.output_type === "presentation" ? (
                              <PresentationArtifact
                                content={artifact.artifact_version.content}
                              />
                            ) : (
                              <pre>{artifact.artifact_version.content}</pre>
                            )}
                          </>
                        )}
                        {artifact.status === "failed" && (
                          <button
                            type="button"
                            onClick={() =>
                              void retryArtifact(artifact.artifact_run_id)
                            }
                          >
                            Retry {label}
                          </button>
                        )}
                      </article>
                    );
                  })}
                </section>
              )}
            </div>
          )}
        </form>
      )}
    </main>
  );
}

type AuthState = "loading" | "signed_out" | "signed_in";

const initializedGoogleApis = new WeakMap<object, string>();

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const buttonContainer = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState<string | null>(null);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId) return;
    let mounted = true;
    let script: HTMLScriptElement | null = null;

    const initialize = () => {
      if (!mounted || !window.google || !buttonContainer.current) return;
      const googleId = window.google.accounts.id;
      if (initializedGoogleApis.get(googleId) !== clientId) {
        googleId.initialize({
          client_id: clientId,
          callback: async (response) => {
            const credential = response.credential;
            if (!credential) {
              setMessage(
                "Google sign-in did not return a credential. Please try again.",
              );
              return;
            }
            setMessage(null);
            try {
              const result = await fetch("/api/auth/google", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ credential }),
              });
              if (!result.ok) {
                setMessage("Sign-in could not be completed. Please try again.");
                return;
              }
              const body: unknown = await result.json();
              if (!isRecord(body) || body.authenticated !== true) {
                setMessage(
                  "Sign-in returned an unexpected response. Please try again.",
                );
                return;
              }
              onSignedIn();
            } catch {
              setMessage(
                "Could not reach AxiomWeave. Check the connection and try again.",
              );
            }
          },
        });
        initializedGoogleApis.set(googleId, clientId);
      }
      buttonContainer.current.replaceChildren();
      googleId.renderButton(buttonContainer.current, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        width: 280,
      });
    };

    if (window.google) {
      initialize();
    } else {
      script = document.querySelector<HTMLScriptElement>(
        "#google-identity-services",
      );
      if (!script) {
        script = document.createElement("script");
        script.id = "google-identity-services";
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.defer = true;
        script.addEventListener("load", initialize, { once: true });
        script.addEventListener(
          "error",
          () => {
            if (mounted)
              setMessage(
                "Google sign-in could not load. Check your connection and configuration, then refresh to retry.",
              );
          },
          { once: true },
        );
        document.head.append(script);
      } else {
        script.addEventListener("load", initialize, { once: true });
      }
    }

    return () => {
      mounted = false;
      script?.removeEventListener("load", initialize);
    };
  }, [clientId, onSignedIn]);

  return (
    <main className="signin-shell">
      <section className="signin-story" aria-labelledby="product-name">
        <p className="signin-kicker">Source-grounded communication</p>
        <p className="signin-brand">AXIOMWEAVE</p>
        <h1 id="product-name">
          Source-Grounded Content Transformation Workspace
        </h1>
        <p className="signin-tagline">
          One source. Many artifacts. Every claim traceable.
        </p>
        <p className="signin-description">
          Transform one authoritative source into traceable, reviewable
          communication artifacts.
        </p>
        <ul className="signin-benefits">
          <li>Multi-output transformation</li>
          <li>Audience and communication controls</li>
          <li>Authenticated workspace</li>
        </ul>
      </section>
      <section className="signin-card" aria-labelledby="signin-heading">
        <p className="eyebrow">AxiomWeave</p>
        <h2 id="signin-heading">Sign in to AxiomWeave</h2>
        {clientId ? (
          <div
            ref={buttonContainer}
            className="google-button"
            aria-label="Continue with Google"
          />
        ) : (
          <p className="signin-message" role="status">
            Google sign-in is not configured. Set SIH_GOOGLE_CLIENT_ID for local
            development.
          </p>
        )}
        {message && (
          <p className="signin-message" role="alert">
            {message}
          </p>
        )}
      </section>
    </main>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    let mounted = true;
    void fetch("/api/auth/session", { credentials: "include" })
      .then(async (response) => {
        if (!mounted) return;
        if (response.status === 401) {
          setAuthState("signed_out");
          return;
        }
        if (!response.ok) throw new Error("session unavailable");
        const body: unknown = await response.json();
        setAuthState(
          isRecord(body) && body.authenticated === true
            ? "signed_in"
            : "signed_out",
        );
      })
      .catch(() => {
        if (mounted) setAuthState("signed_out");
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function signOut(): Promise<boolean> {
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) return false;
      setAuthState("signed_out");
      return true;
    } catch {
      return false;
    }
  }

  if (authState === "loading") {
    return (
      <main className="signin-loading" role="status">
        Checking your AxiomWeave session…
      </main>
    );
  }
  if (authState === "signed_out") {
    return <SignIn onSignedIn={() => setAuthState("signed_in")} />;
  }
  return <Workspace onLogout={signOut} />;
}
