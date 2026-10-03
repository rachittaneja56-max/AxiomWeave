import { useRef, useState, type DragEvent, type FormEvent } from "react";
import {
  Check,
  Clapperboard,
  FileCheck2,
  FileImage,
  FileText,
  LoaderCircle,
  Megaphone,
  MessageCircle,
  Presentation,
  Upload,
  X,
} from "lucide-react";
import { api, ApiError } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import {
  extractionError,
  deriveTransformationTitle,
  isExtractedText,
  isGeneratedArtifact,
  isRecord,
  isSavedTransformation,
  sourceCharacterCount,
  validationMessage,
} from "../utils";
import {
  OUTPUT_TYPES,
  type DetailLevel,
  type GeneratedArtifact,
  type OutputType,
  type SavedTransformation,
  type SourceFileMetadata,
  type TransformationRequest,
} from "../types";

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

const OUTPUT_ICONS: Record<OutputType, typeof FileText> = {
  executive_summary: FileCheck2,
  linkedin_post: Megaphone,
  x_post: MessageCircle,
  advisory: FileText,
  presentation: Presentation,
  infographic: FileImage,
  video_package: Clapperboard,
};

type Phase = "idle" | "saving" | "generating" | "ready";
type SourceMode = "paste" | "upload" | "url";

export function NewTransformationScreen({
  onOpenReview,
  onBack,
}: {
  onOpenReview: (
    id: number,
    title: string,
    sourceVersion: number,
    outputType?: OutputType,
  ) => void;
  onBack: () => void;
}) {
  const [request, setRequest] =
    useState<TransformationRequest>(INITIAL_REQUEST);
  const [sourceMode, setSourceMode] = useState<SourceMode>("paste");
  const [sourceFile, setSourceFile] = useState<SourceFileMetadata | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [saved, setSaved] = useState<SavedTransformation | null>(null);
  const [artifacts, setArtifacts] = useState<GeneratedArtifact[]>([]);
  const [retryingArtifact, setRetryingArtifact] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const isLocked =
    phase === "saving" || phase === "generating" || Boolean(saved);

  function updateRequest<K extends keyof TransformationRequest>(
    field: K,
    value: TransformationRequest[K],
  ) {
    setRequest((current) => ({ ...current, [field]: value }));
    setError(null);
  }

  function toggleOutput(outputType: OutputType, checked: boolean) {
    const outputTypes = checked
      ? [...request.output_types, outputType]
      : request.output_types.filter((item) => item !== outputType);
    updateRequest("output_types", outputTypes);
  }

  function switchSourceMode(mode: SourceMode) {
    if (isLocked || isExtracting) return;
    setSourceMode(mode);
    setRequest((current) => ({ ...current, source_text: "" }));
    setSourceFile(null);
    setSourceUrl("");
    if (fileInput.current) fileInput.current.value = "";
    setError(null);
  }

  function clearUploadedFile() {
    setSourceFile(null);
    setRequest((current) => ({ ...current, source_text: "" }));
    if (fileInput.current) fileInput.current.value = "";
    setError(null);
  }

  async function extractSourceFile(file: File | undefined) {
    if (!file || isLocked) return;
    setError(null);
    setSourceFile(null);
    setRequest((current) => ({ ...current, source_text: "" }));
    setIsExtracting(true);
    try {
      const body = await api.extractTextFile(file);
      if (!isExtractedText(body)) {
        setError("The file could not be read in the expected format.");
        return;
      }
      setRequest((current) => ({ ...current, source_text: body.source_text }));
      setSourceFile({
        filename: body.filename,
        character_count: body.character_count,
        ocr_used: body.ocr_used,
        ...(body.source_version_id !== undefined
          ? { source_version_id: body.source_version_id }
          : {}),
      });
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(extractionError(requestError.body, requestError.status));
      } else {
        setError(
          "Could not reach the service to read this file. Check the connection and try again.",
        );
      }
    } finally {
      setIsExtracting(false);
    }
  }

  async function importUrl() {
    if (isLocked || isExtracting) return;
    setError(null);
    setSourceFile(null);
    setRequest((current) => ({ ...current, source_text: "" }));
    setIsExtracting(true);
    try {
      const body = await api.extractUrl(sourceUrl);
      if (
        !isRecord(body) ||
        typeof body.source_text !== "string" ||
        typeof body.title !== "string" ||
        typeof body.character_count !== "number"
      ) {
        setError("The page could not be read in the expected format.");
        return;
      }
      setRequest((current) => ({
        ...current,
        source_text: body.source_text as string,
      }));
      setSourceFile({
        filename: "Imported page: " + body.title,
        character_count: body.character_count,
        ocr_used: false,
        ...(Number.isInteger(body.source_version_id)
          ? { source_version_id: Number(body.source_version_id) }
          : {}),
      });
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(extractionError(requestError.body, requestError.status));
      } else {
        setError(
          "Could not reach the service to read this page. Check the connection and try again.",
        );
      }
    } finally {
      setIsExtracting(false);
    }
  }

  async function generateFromSaved(transformation: SavedTransformation) {
    setGenerationError(null);
    setPhase("generating");
    try {
      const body = await api.generate(transformation.transformation_run_id);
      if (
        !isRecord(body) ||
        !["succeeded", "partial_failure", "running"].includes(
          String(body.status),
        ) ||
        !Array.isArray(body.artifacts) ||
        !body.artifacts.every(isGeneratedArtifact)
      ) {
        throw new Error("unexpected generation result");
      }
      setArtifacts(body.artifacts);
      const successful = body.artifacts.filter(
        (artifact: GeneratedArtifact) => artifact.status === "succeeded",
      );
      if (body.artifacts.length > 0) {
        const initial =
          OUTPUT_TYPES.map(({ value }) =>
            successful.find(
              (artifact: GeneratedArtifact) => artifact.output_type === value,
            ),
          ).find(Boolean) ?? body.artifacts[0];
        queueMicrotask(() =>
          onOpenReview(
            transformation.transformation_run_id,
            deriveTransformationTitle(request.source_text),
            transformation.source_version.version_number,
            initial.output_type,
          ),
        );
      }
    } catch (requestError) {
      if (
        requestError instanceof ApiError &&
        isRecord(requestError.body) &&
        isRecord(requestError.body.error) &&
        requestError.body.error.code === "generation_not_configured"
      ) {
        setGenerationError("Generation is not configured on this server.");
      } else {
        setGenerationError(
          "These artifacts could not be generated. Please try again.",
        );
      }
    } finally {
      setPhase("ready");
    }
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setGenerationError(null);
    if (!request.source_text.trim()) {
      setError("Add source text before generating artifacts.");
      return;
    }
    if (!request.output_types.length) {
      setError("Choose at least one artifact to generate.");
      return;
    }

    setPhase("saving");
    try {
      const body = await api.createTransformation({
        ...request,
        ...(sourceFile?.source_version_id !== undefined
          ? { source_version_id: sourceFile.source_version_id }
          : {}),
      });
      if (!isSavedTransformation(body)) {
        setError(
          "The service returned an unexpected save response. Please retry.",
        );
        setPhase("idle");
        return;
      }
      setSaved(body);
      await generateFromSaved(body);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 422) {
        setError(validationMessage(requestError.body));
      } else if (requestError instanceof ApiError) {
        setError("Your source could not be saved. Please retry.");
      } else {
        setError(
          "Your source could not be saved. Check the connection and try again.",
        );
      }
      setPhase("idle");
    }
  }

  async function retryArtifact(artifactRunId: number) {
    setRetryingArtifact(artifactRunId);
    setGenerationError(null);
    try {
      const body = await api.retryArtifact(artifactRunId);
      if (!isGeneratedArtifact(body))
        throw new Error("unexpected retry result");
      const next = artifacts.map((artifact) =>
        artifact.artifact_run_id === artifactRunId ? body : artifact,
      );
      setArtifacts(next);
      if (
        next.length === saved?.output_types.length &&
        next.every((artifact) => artifact.status === "succeeded") &&
        saved
      ) {
        const initial = OUTPUT_TYPES.map(({ value }) =>
          next.find((artifact) => artifact.output_type === value),
        ).find(Boolean);
        queueMicrotask(() =>
          onOpenReview(
            saved.transformation_run_id,
            deriveTransformationTitle(request.source_text),
            saved.source_version.version_number,
            initial?.output_type,
          ),
        );
      }
    } catch {
      setGenerationError(
        "This artifact could not be retried. Please try again.",
      );
    } finally {
      setRetryingArtifact(null);
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    if (isLocked || isExtracting) return;
    void extractSourceFile(event.dataTransfer.files[0]);
  }

  const sourceCount = sourceCharacterCount(request.source_text);

  return (
    <section className="composer-screen" aria-label="New transformation">
      <form
        className="composer-form"
        onSubmit={(event) => void submitRequest(event)}
      >
        <div className="composer-main">
          <section
            className="source-editor-panel"
            aria-labelledby="source-heading"
          >
            <div className="panel-heading">
              <div>
                <p className="eyebrow">01 · Start with a source</p>
                <h2 id="source-heading">Your source</h2>
                <p>Use the material you want every artifact to follow.</p>
              </div>
              <span className="source-kind">
                <span className="source-kind__dot" />
                Source
              </span>
            </div>
            <div
              className="source-tabs"
              role="tablist"
              aria-label="Source input method"
            >
              <button
                type="button"
                role="tab"
                aria-selected={sourceMode === "paste"}
                className={sourceMode === "paste" ? "is-selected" : ""}
                onClick={() => switchSourceMode("paste")}
                disabled={isLocked || isExtracting}
              >
                Paste text
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={sourceMode === "upload"}
                className={sourceMode === "upload" ? "is-selected" : ""}
                onClick={() => switchSourceMode("upload")}
                disabled={isLocked || isExtracting}
              >
                Upload a file
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={sourceMode === "url"}
                className={sourceMode === "url" ? "is-selected" : ""}
                onClick={() => switchSourceMode("url")}
                disabled={isLocked || isExtracting}
              >
                Import from URL
              </button>
            </div>
            {sourceMode === "paste" ? (
              <label className="source-text-wrap" htmlFor="source-text">
                <span className="visually-hidden">Text source</span>
                <textarea
                  id="source-text"
                  rows={12}
                  maxLength={20_000}
                  value={request.source_text}
                  onChange={(event) =>
                    updateRequest("source_text", event.target.value)
                  }
                  placeholder="Paste a report, announcement, policy, or other source material…"
                  disabled={isLocked}
                />
              </label>
            ) : sourceMode === "url" ? (
              <div className="url-import-panel">
                {sourceFile ? (
                  <div className="upload-file" role="status" aria-live="polite">
                    <span className="upload-file__icon">
                      <FileText />
                    </span>
                    <span className="upload-file__name">
                      <strong>{sourceFile.filename}</strong>
                      <small>
                        {sourceFile.character_count.toLocaleString()} characters
                      </small>
                    </span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Remove imported page"
                      onClick={clearUploadedFile}
                      disabled={isLocked}
                    >
                      <X aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <div className="url-import-form">
                    <label htmlFor="source-url">Public page URL</label>
                    <div className="url-import-form__row">
                      <input
                        id="source-url"
                        type="url"
                        inputMode="url"
                        placeholder="https://example.com/article"
                        value={sourceUrl}
                        onChange={(event) => setSourceUrl(event.target.value)}
                        disabled={isLocked || isExtracting}
                      />
                      <button
                        type="button"
                        className="button-secondary"
                        onClick={() => void importUrl()}
                        disabled={isLocked || isExtracting || !sourceUrl.trim()}
                      >
                        {isExtracting ? (
                          <LoaderCircle className="status-spin" />
                        ) : null}
                        {isExtracting ? "Reading page" : "Read public page"}
                      </button>
                    </div>
                    <p>
                      One public HTTP or HTTPS page. Login pages and
                      JavaScript-rendered pages may not be available.
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div
                className={"upload-dropzone" + (sourceFile ? " has-file" : "")}
              >
                <input
                  ref={fileInput}
                  id="source-file"
                  aria-label="Upload source file"
                  className="visually-hidden"
                  type="file"
                  accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(event) =>
                    void extractSourceFile(event.target.files?.[0])
                  }
                  disabled={isLocked || isExtracting}
                />
                {sourceFile ? (
                  <div className="upload-file" role="status" aria-live="polite">
                    <span className="upload-file__icon">
                      <FileText />
                    </span>
                    <span className="upload-file__name">
                      <strong>{sourceFile.filename}</strong>
                      <small>
                        {sourceFile.character_count.toLocaleString()} characters
                      </small>
                      {sourceFile.ocr_used && (
                        <small className="ocr-used-note">
                          OCR used on scanned pages
                        </small>
                      )}
                    </span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Remove uploaded source"
                      onClick={clearUploadedFile}
                      disabled={isLocked}
                    >
                      <X aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <label
                    className="upload-prompt"
                    htmlFor="source-file"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={onDrop}
                  >
                    <span className="upload-prompt__icon">
                      {isExtracting ? (
                        <LoaderCircle className="status-spin" />
                      ) : (
                        <Upload />
                      )}
                    </span>
                    <strong>
                      {isExtracting
                        ? "Reading document…"
                        : "Drop a document here"}
                    </strong>
                    <span>or browse your device</span>
                    <small>
                      TXT, MD, DOCX or PDF · source text up to 20,000 characters
                    </small>
                  </label>
                )}
              </div>
            )}
            <div className="source-editor-footer">
              <p>
                Source material is stored as an immutable version when you
                continue.
              </p>
              <span>{sourceCount.toLocaleString()} / 20,000</span>
            </div>
          </section>

          <aside className="settings-panel" aria-labelledby="settings-heading">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">02 · Shape the message</p>
                <h2 id="settings-heading">Communication settings</h2>
              </div>
              <span className="settings-glyph" aria-hidden="true">
                Aa
              </span>
            </div>
            <div className="settings-fields">
              <div className="field">
                <label htmlFor="audience">Audience</label>
                <input
                  id="audience"
                  value={request.audience}
                  onChange={(event) =>
                    updateRequest("audience", event.target.value)
                  }
                  disabled={isLocked}
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
                  disabled={isLocked}
                />
              </div>
              <div className="field field--split">
                <div>
                  <label htmlFor="detail-level">Detail</label>
                  <select
                    id="detail-level"
                    value={request.detail_level}
                    onChange={(event) =>
                      updateRequest(
                        "detail_level",
                        event.target.value as DetailLevel,
                      )
                    }
                    disabled={isLocked}
                  >
                    <option value="brief">Brief</option>
                    <option value="standard">Standard</option>
                    <option value="detailed">Detailed</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="language">Language</label>
                  <input
                    id="language"
                    value={request.language}
                    onChange={(event) =>
                      updateRequest("language", event.target.value)
                    }
                    disabled={isLocked}
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor="objective">Objective</label>
                <input
                  id="objective"
                  value={request.objective}
                  onChange={(event) =>
                    updateRequest("objective", event.target.value)
                  }
                  disabled={isLocked}
                />
              </div>
              <div className="field">
                <label htmlFor="style">Style</label>
                <input
                  id="style"
                  value={request.style}
                  onChange={(event) =>
                    updateRequest("style", event.target.value)
                  }
                  disabled={isLocked}
                />
              </div>
            </div>
            <details className="supporting-context">
              <summary>
                Supporting context <span>Optional</span>
              </summary>
              <label htmlFor="supporting-context">Additional guidance</label>
              <textarea
                id="supporting-context"
                rows={4}
                maxLength={5000}
                value={request.supporting_context}
                onChange={(event) =>
                  updateRequest("supporting_context", event.target.value)
                }
                placeholder="Add audience-specific or operational guidance"
                disabled={isLocked}
              />
              <p>
                Context can guide the writing, but it is not treated as source
                evidence.
              </p>
            </details>
          </aside>
        </div>

        <section className="output-picker" aria-labelledby="outputs-heading">
          <div className="output-picker__heading">
            <div>
              <p className="eyebrow">03 · Choose what you need</p>
              <h2 id="outputs-heading">Artifacts</h2>
              <p>
                Select one or more formats. Each uses the same source and
                settings.
              </p>
            </div>
            <span className="selection-count">
              {request.output_types.length} selected
            </span>
          </div>
          <fieldset className="output-card-grid">
            <legend className="visually-hidden">Choose artifact types</legend>
            {OUTPUT_TYPES.map((output) => {
              const Icon = OUTPUT_ICONS[output.value];
              const checked = request.output_types.includes(output.value);
              return (
                <label
                  className={"output-card" + (checked ? " is-selected" : "")}
                  key={output.value}
                >
                  <input
                    type="checkbox"
                    aria-label={output.label}
                    name="output_types"
                    value={output.value}
                    checked={checked}
                    onChange={(event) =>
                      toggleOutput(output.value, event.target.checked)
                    }
                    disabled={isLocked}
                  />
                  <span className="output-card__icon">
                    <Icon />
                  </span>
                  <span className="output-card__copy">
                    <strong>{output.label}</strong>
                    <small>{output.description}</small>
                  </span>
                  <span className="output-card__check">
                    {checked && <Check aria-hidden="true" />}
                  </span>
                </label>
              );
            })}
          </fieldset>
        </section>

        <div className="composer-submit-row">
          <div className="composer-submit-copy">
            <span className="lineage-indicator" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <p>
              Your source will be saved first, then your selected artifacts will
              be prepared.
            </p>
          </div>
          {saved ? (
            <button type="button" className="button-secondary" onClick={onBack}>
              Back to transformations
            </button>
          ) : (
            <button
              type="submit"
              className="button-primary"
              disabled={
                phase === "saving" || phase === "generating" || isExtracting
              }
            >
              {phase === "saving" ? "Saving source…" : "Generate artifacts"}
              {phase === "saving" || phase === "generating" ? (
                <LoaderCircle className="status-spin" aria-hidden="true" />
              ) : (
                <Check aria-hidden="true" />
              )}
            </button>
          )}
        </div>

        {error && (
          <p className="notice notice--error" role="alert">
            {error}
          </p>
        )}
        {phase === "generating" && (
          <section
            className="generation-progress"
            aria-live="polite"
            role="status"
          >
            <div className="progress-heading">
              <LoaderCircle className="status-spin" aria-hidden="true" />
              <div>
                <strong>Preparing your artifacts</strong>
                <p>
                  Each selected format is being created from the same source.
                </p>
              </div>
            </div>
            <div className="generation-list">
              {request.output_types.map((outputType) => (
                <div className="generation-row" key={outputType}>
                  <span className="generation-row__dot" />
                  <span>
                    {
                      OUTPUT_TYPES.find((output) => output.value === outputType)
                        ?.label
                    }
                  </span>
                  <small>In progress</small>
                </div>
              ))}
            </div>
          </section>
        )}
        {saved && phase === "ready" && (
          <section
            className="generation-results"
            aria-labelledby="results-heading"
          >
            <div className="generation-results__heading">
              <div>
                <p className="eyebrow">
                  Source V{saved.source_version.version_number}
                </p>
                <h2 id="results-heading">Generation results</h2>
              </div>
              <button
                type="button"
                className="button-secondary"
                onClick={() =>
                  onOpenReview(
                    saved.transformation_run_id,
                    deriveTransformationTitle(request.source_text),
                    saved.source_version.version_number,
                    artifacts.find(
                      (artifact) => artifact.status === "succeeded",
                    )?.output_type,
                  )
                }
              >
                Review successful artifacts
              </button>
            </div>
            {generationError && (
              <div className="notice notice--error" role="alert">
                <p>{generationError}</p>
                {artifacts.length === 0 && (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void generateFromSaved(saved)}
                  >
                    Try again
                  </button>
                )}
              </div>
            )}
            <div className="generated-artifact-list">
              {(artifacts.length
                ? artifacts
                : saved.output_types.map((outputType) => ({
                    artifact_run_id: outputType,
                    output_type: outputType,
                    status: "pending" as const,
                    artifact_version: null,
                  }))
              ).map((artifact) => {
                const outputType = artifact.output_type;
                const label =
                  OUTPUT_TYPES.find((output) => output.value === outputType)
                    ?.label ?? "Artifact";
                const state =
                  artifact.status === "succeeded"
                    ? "Ready for review"
                    : artifact.status === "failed"
                      ? "Needs attention"
                      : artifact.status === "running"
                        ? "Generating"
                        : "Waiting";
                return (
                  <article
                    className="generated-artifact-row"
                    key={artifact.artifact_run_id}
                  >
                    <div className="generated-artifact-row__heading">
                      <span className="generated-artifact-row__icon">
                        {state === "Ready for review" ? (
                          <Check aria-hidden="true" />
                        ) : (
                          <FileText aria-hidden="true" />
                        )}
                      </span>
                      <div>
                        <h3>{label}</h3>
                        <StatusBadge status={state} compact />
                      </div>
                      {artifact.status === "failed" && (
                        <button
                          type="button"
                          className="button-secondary"
                          onClick={() =>
                            void retryArtifact(
                              artifact.artifact_run_id as number,
                            )
                          }
                          disabled={
                            retryingArtifact === artifact.artifact_run_id
                          }
                        >
                          <LoaderCircle
                            className={
                              retryingArtifact === artifact.artifact_run_id
                                ? "status-spin"
                                : ""
                            }
                            aria-hidden="true"
                          />
                          Retry
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}
      </form>
    </section>
  );
}
