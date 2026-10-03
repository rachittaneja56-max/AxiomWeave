import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  FileText,
  Pencil,
  RefreshCw,
  X,
  GitBranch,
} from "lucide-react";
import type {
  OutputType,
  InfographicDocument,
  ReviewArtifactRun,
  ReviewArtifactVersion,
  VideoPackageDocument,
} from "../types";
import {
  outputLabel,
  parseInfographic,
  parsePresentation,
  parseVideoPackage,
} from "../utils";
import { MarkdownDocument } from "../components/MarkdownDocument";
import { StatusBadge } from "../components/StatusBadge";
import { MediaWorkflowPanel } from "./MediaWorkflowPanel";
import type { PresentationDocument } from "../types";
import {
  InfographicEditor,
  InfographicViewer,
  VideoPackageEditor,
  VideoPackageViewer,
} from "./StructuredArtifactViewers";

function PresentationEditor({
  value,
  activeIndex,
  onActiveIndexChange,
  onChange,
}: {
  value: PresentationDocument;
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onChange: (value: PresentationDocument) => void;
}) {
  const slide = value.slides[activeIndex];
  function updateSlide<K extends keyof (typeof value.slides)[number]>(
    field: K,
    nextValue: (typeof value.slides)[number][K],
  ) {
    onChange({
      ...value,
      slides: value.slides.map((item, index) =>
        index === activeIndex ? { ...item, [field]: nextValue } : item,
      ),
    });
  }
  return (
    <div className="presentation-editor">
      <header className="presentation-editor__bar">
        <div>
          <strong>Editing presentation</strong>
          <label htmlFor="presentation-title">Deck title</label>
          <input
            id="presentation-title"
            value={value.title}
            onChange={(event) =>
              onChange({ ...value, title: event.target.value })
            }
          />
        </div>
      </header>
      <div className="presentation-editor__workspace">
        <nav className="slide-rail" aria-label="Edit slides">
          <p className="eyebrow">{value.slides.length} slides</p>
          {value.slides.map((item, index) => (
            <button
              type="button"
              key={index}
              className={index === activeIndex ? "is-active" : ""}
              aria-current={index === activeIndex ? "page" : undefined}
              onClick={() => onActiveIndexChange(index)}
            >
              <span className="slide-thumbnail">
                <small>{index + 1}</small>
                <strong>{item.title}</strong>
              </span>
              <span>Slide {index + 1}</span>
            </button>
          ))}
        </nav>
        <div className="presentation-editor__content">
          <div className="slide-canvas slide-canvas--16x9">
            <div className="slide-canvas__eyebrow">{value.title}</div>
            <span className="slide-canvas__number">
              {String(activeIndex + 1).padStart(2, "0")}
            </span>
            <h3>{slide.title || "Slide title"}</h3>
            <p className="slide-canvas__message">{slide.key_message}</p>
            <ul>
              {slide.bullets.filter(Boolean).map((bullet, index) => (
                <li key={index}>{bullet}</li>
              ))}
            </ul>
            <div className="slide-visual-note">
              <span>Visual direction</span>
              <p>{slide.visual_recommendation}</p>
            </div>
          </div>
          <fieldset className="presentation-editor__slide">
            <legend>Edit slide {activeIndex + 1}</legend>
            <label htmlFor="slide-title">Title</label>
            <input
              id="slide-title"
              value={slide.title}
              onChange={(event) => updateSlide("title", event.target.value)}
            />
            <label htmlFor="slide-message">Key message</label>
            <textarea
              id="slide-message"
              rows={2}
              value={slide.key_message}
              onChange={(event) =>
                updateSlide("key_message", event.target.value)
              }
            />
            <label htmlFor="slide-bullets">Bullets (one per line)</label>
            <textarea
              id="slide-bullets"
              rows={4}
              value={slide.bullets.join("\n")}
              onChange={(event) =>
                updateSlide("bullets", event.target.value.split("\n"))
              }
            />
            <label htmlFor="slide-visual">Visual recommendation</label>
            <textarea
              id="slide-visual"
              rows={2}
              value={slide.visual_recommendation}
              onChange={(event) =>
                updateSlide("visual_recommendation", event.target.value)
              }
            />
            <label htmlFor="slide-notes">Speaker notes</label>
            <textarea
              id="slide-notes"
              rows={4}
              value={slide.speaker_notes}
              onChange={(event) =>
                updateSlide("speaker_notes", event.target.value)
              }
            />
          </fieldset>
        </div>
      </div>
    </div>
  );
}

function PresentationViewer({ content }: { content: string }) {
  const presentation = parsePresentation(content);
  const [activeSlide, setActiveSlide] = useState(0);
  useEffect(() => setActiveSlide(0), [content]);
  if (!presentation) {
    return (
      <div className="document-empty">
        <FileText aria-hidden="true" />
        <p>This presentation could not be displayed.</p>
      </div>
    );
  }
  const slide = presentation.slides[activeSlide];
  return (
    <div className="presentation-viewer">
      <nav className="slide-rail" aria-label="Slides">
        <p className="eyebrow">{presentation.slides.length} slides</p>
        {presentation.slides.map((item, index) => (
          <button
            type="button"
            key={index}
            className={index === activeSlide ? "is-active" : ""}
            aria-current={index === activeSlide ? "page" : undefined}
            onClick={() => setActiveSlide(index)}
          >
            <span
              className="slide-thumbnail"
              aria-label={`Slide ${index + 1}: ${item.title}`}
            >
              <small>{index + 1}</small>
              <strong>{item.title}</strong>
            </span>
            <span>Slide {index + 1}</span>
          </button>
        ))}
      </nav>
      <div className="slide-review">
        <div className="slide-canvas slide-canvas--16x9">
          <div className="slide-canvas__eyebrow">{presentation.title}</div>
          <span className="slide-canvas__number">
            {String(activeSlide + 1).padStart(2, "0")}
          </span>
          <h3>{slide.title}</h3>
          <p className="slide-canvas__message">{slide.key_message}</p>
          <ul>
            {slide.bullets.map((bullet, index) => (
              <li key={index}>{bullet}</li>
            ))}
          </ul>
          <div className="slide-visual-note">
            <span>Visual direction</span>
            <p>{slide.visual_recommendation}</p>
          </div>
        </div>
        <div className="slide-controls">
          <span>
            Slide {activeSlide + 1} of {presentation.slides.length}
          </span>
          <div>
            <button
              type="button"
              className="icon-button"
              aria-label="Previous slide"
              onClick={() =>
                setActiveSlide(
                  (index) =>
                    (index - 1 + presentation.slides.length) %
                    presentation.slides.length,
                )
              }
            >
              <ChevronLeft aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label="Next slide"
              onClick={() =>
                setActiveSlide(
                  (index) => (index + 1) % presentation.slides.length,
                )
              }
            >
              <ChevronRight aria-hidden="true" />
            </button>
          </div>
        </div>
        <details className="speaker-notes">
          <summary>
            Speaker notes <ChevronDown aria-hidden="true" />
          </summary>
          <p>{slide.speaker_notes}</p>
        </details>
      </div>
    </div>
  );
}

export function ArtifactViewer({
  artifact,
  version,
  projectTitle,
  currentSourceVersion,
  isLatest,
  busy,
  exportStatus,
  onEdit,
  onSave,
  onCancelEdit,
  onRegenerate,
  onRetry,
  onReviewStatus,
  onCopy,
  onDownload,
  onPowerpointExport,
  onTraceability,
}: {
  artifact: ReviewArtifactRun;
  version: ReviewArtifactVersion | null;
  projectTitle: string;
  currentSourceVersion: number;
  isLatest: boolean;
  busy: boolean;
  exportStatus: string | null;
  onEdit: () => void;
  onSave: (content: string) => void;
  onCancelEdit: () => void;
  onRegenerate: () => void;
  onRetry: () => void;
  onReviewStatus: (status: "accepted" | "rejected") => void;
  onCopy: (outputType: OutputType, content: string) => void;
  onDownload: (outputType: OutputType, content: string) => void;
  onPowerpointExport: (content: string) => void;
  onTraceability: (trigger: HTMLButtonElement) => void;
}) {
  const [editContent, setEditContent] = useState(version?.content ?? "");
  const [presentationDraft, setPresentationDraft] = useState(() =>
    parsePresentation(version?.content ?? ""),
  );
  const [infographicDraft, setInfographicDraft] =
    useState<InfographicDocument | null>(() =>
      parseInfographic(version?.content ?? ""),
    );
  const [videoPackageDraft, setVideoPackageDraft] =
    useState<VideoPackageDocument | null>(() =>
      parseVideoPackage(version?.content ?? ""),
    );
  const [editing, setEditing] = useState(false);
  const [activeEditSlideIndex, setActiveEditSlideIndex] = useState(0);
  const label = outputLabel(artifact.output_type);

  useEffect(() => {
    setEditContent(version?.content ?? "");
    setPresentationDraft(parsePresentation(version?.content ?? ""));
    setInfographicDraft(parseInfographic(version?.content ?? ""));
    setVideoPackageDraft(parseVideoPackage(version?.content ?? ""));
    setEditing(false);
  }, [artifact.artifact_run_id, version?.id, version?.content]);

  function beginEdit() {
    setEditContent(version?.content ?? "");
    setPresentationDraft(parsePresentation(version?.content ?? ""));
    setInfographicDraft(parseInfographic(version?.content ?? ""));
    setVideoPackageDraft(parseVideoPackage(version?.content ?? ""));
    setEditing(true);
    setActiveEditSlideIndex(0);
    onEdit();
  }

  function cancelEdit() {
    setEditing(false);
    onCancelEdit();
  }

  return (
    <section className="artifact-viewer" aria-labelledby="artifact-title">
      <header className="artifact-viewer__header">
        <div>
          <h2 id="artifact-title">{label}</h2>
          <p className="artifact-project-meta">
            {projectTitle} <span aria-hidden="true">·</span> Source V
            {currentSourceVersion}
            {version && <span> · Version {version.version_number}</span>}
          </p>
          {artifact.output_type === "infographic" && (
            <p className="artifact-capability">
              Editable infographic specification
            </p>
          )}
          {artifact.output_type === "video_package" && (
            <p className="artifact-capability">
              Editable video production package
            </p>
          )}
          {version && (
            <StatusBadge
              status={
                version.review_status === "draft"
                  ? "Ready for review"
                  : version.review_status === "accepted"
                    ? "Accepted"
                    : "Rejected"
              }
              compact
            />
          )}
        </div>
        {version && isLatest && !editing && (
          <div className="artifact-toolbar" aria-label="Artifact actions">
            {artifact.output_type === "presentation" && (
              <button
                type="button"
                className="button-secondary"
                onClick={() => onPowerpointExport(version.content)}
              >
                <Download aria-hidden="true" />
                Download PowerPoint
              </button>
            )}
            <button
              type="button"
              className="button-primary button-primary--small"
              onClick={beginEdit}
            >
              <Pencil aria-hidden="true" />
              Edit
            </button>
            <button
              type="button"
              className="button-secondary traceability-action"
              onClick={(event) => onTraceability(event.currentTarget)}
            >
              <GitBranch aria-hidden="true" />
              Traceability
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={onRegenerate}
              disabled={busy}
            >
              <RefreshCw aria-hidden="true" />
              Regenerate
            </button>
            {version.review_status === "draft" ? (
              <button
                type="button"
                className="button-secondary artifact-accept"
                onClick={() => onReviewStatus("accepted")}
                disabled={busy}
              >
                <Check aria-hidden="true" />
                Accept
              </button>
            ) : version.review_status === "accepted" ? (
              <span className="artifact-accepted">
                <Check aria-hidden="true" />
                Accepted
              </span>
            ) : null}
            <button
              type="button"
              className="icon-button"
              aria-label="Copy artifact"
              onClick={() => onCopy(artifact.output_type, version.content)}
            >
              <Copy aria-hidden="true" />
            </button>
            <details className="artifact-more">
              <summary aria-label="More artifact actions">
                <ChevronDown aria-hidden="true" />
                <span>More</span>
              </summary>
              <div className="artifact-more__menu">
                <button
                  type="button"
                  onClick={() =>
                    onDownload(artifact.output_type, version.content)
                  }
                >
                  <Download aria-hidden="true" />
                  Download Markdown
                </button>
                {version.review_status === "draft" && (
                  <>
                    <button
                      type="button"
                      onClick={() => onReviewStatus("rejected")}
                      disabled={busy}
                    >
                      <X aria-hidden="true" />
                      Reject
                    </button>
                  </>
                )}
              </div>
            </details>
          </div>
        )}
      </header>
      {artifact.status === "failed" && !version && (
        <div className="artifact-failure" role="status">
          <div>
            <strong>This artifact needs another attempt.</strong>
            <p>You can retry it without restarting the other artifacts.</p>
          </div>
          <button
            type="button"
            className="button-secondary"
            onClick={onRetry}
            disabled={busy}
          >
            <RefreshCw aria-hidden="true" />
            Retry artifact
          </button>
        </div>
      )}
      {version ? (
        editing ? (
          <div className="artifact-editor">
            {artifact.output_type === "presentation" ? (
              presentationDraft ? (
                <PresentationEditor
                  value={presentationDraft}
                  activeIndex={activeEditSlideIndex}
                  onActiveIndexChange={setActiveEditSlideIndex}
                  onChange={setPresentationDraft}
                />
              ) : (
                <p className="notice notice--error" role="alert">
                  This presentation could not be opened in the structured
                  editor.
                </p>
              )
            ) : artifact.output_type === "infographic" ? (
              infographicDraft ? (
                <InfographicEditor
                  value={infographicDraft}
                  onChange={setInfographicDraft}
                />
              ) : (
                <p className="notice notice--error" role="alert">
                  This infographic specification could not be opened in the
                  structured editor.
                </p>
              )
            ) : artifact.output_type === "video_package" ? (
              videoPackageDraft ? (
                <VideoPackageEditor
                  value={videoPackageDraft}
                  onChange={setVideoPackageDraft}
                />
              ) : (
                <p className="notice notice--error" role="alert">
                  This video package could not be opened in the structured
                  editor.
                </p>
              )
            ) : (
              <>
                <label htmlFor="artifact-editor">Edit {label}</label>
                <textarea
                  id="artifact-editor"
                  rows={18}
                  value={editContent}
                  onChange={(event) => setEditContent(event.target.value)}
                />
              </>
            )}
            <div className="presentation-editor__actions">
              <p className="field-hint">Saving creates a new version.</p>
              <div className="review-actions">
                <button
                  type="button"
                  className="button-primary"
                  onClick={() =>
                    onSave(
                      artifact.output_type === "presentation" &&
                        presentationDraft
                        ? JSON.stringify(presentationDraft)
                        : artifact.output_type === "infographic" &&
                            infographicDraft
                          ? JSON.stringify(infographicDraft)
                          : artifact.output_type === "video_package" &&
                              videoPackageDraft
                            ? JSON.stringify(videoPackageDraft)
                            : editContent,
                    )
                  }
                  disabled={
                    busy ||
                    (artifact.output_type === "presentation" &&
                      !presentationDraft) ||
                    (artifact.output_type === "infographic" &&
                      !infographicDraft) ||
                    (artifact.output_type === "video_package" &&
                      !videoPackageDraft)
                  }
                >
                  Save version
                </button>
                <button
                  type="button"
                  className="button-secondary"
                  onClick={cancelEdit}
                  disabled={busy}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        ) : artifact.output_type === "presentation" ? (
          <PresentationViewer content={version.content} />
        ) : artifact.output_type === "infographic" ? (
          infographicDraft ? (
            <InfographicViewer value={infographicDraft} />
          ) : (
            <div className="document-empty" role="alert">
              <FileText aria-hidden="true" />
              <p>This infographic specification could not be displayed.</p>
            </div>
          )
        ) : artifact.output_type === "video_package" ? (
          videoPackageDraft ? (
            <VideoPackageViewer value={videoPackageDraft} />
          ) : (
            <div className="document-empty" role="alert">
              <FileText aria-hidden="true" />
              <p>This video package could not be displayed.</p>
            </div>
          )
        ) : (
          <article
            className={
              "artifact-document" +
              (artifact.output_type === "x_post"
                ? " artifact-document--x-post"
                : "")
            }
          >
            {artifact.output_type === "x_post" && (
              <p
                className="x-post-character-count"
                aria-label="Character count"
              >
                {Array.from(version.content.trim()).length} / 280 characters
              </p>
            )}
            <MarkdownDocument content={version.content} />
          </article>
        )
      ) : artifact.status === "running" || artifact.status === "pending" ? (
        <div className="artifact-loading" role="status">
          <span className="loading-mark" aria-hidden="true" />
          <p>
            {artifact.status === "running"
              ? "This artifact is being prepared…"
              : "This artifact is waiting to be prepared."}
          </p>
        </div>
      ) : artifact.status !== "failed" ? (
        <div className="document-empty">
          <FileText aria-hidden="true" />
          <p>No artifact version is available yet.</p>
        </div>
      ) : null}
      {exportStatus && (
        <p className="visually-hidden" role="status">
          {exportStatus}
        </p>
      )}
      <MediaWorkflowPanel outputType={artifact.output_type} version={version} />
    </section>
  );
}
