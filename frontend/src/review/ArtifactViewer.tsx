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
} from "lucide-react";
import type {
  OutputType,
  ReviewArtifactRun,
  ReviewArtifactVersion,
} from "../types";
import { outputLabel, parsePresentation } from "../utils";
import { MarkdownDocument } from "../components/MarkdownDocument";
import { StatusBadge } from "../components/StatusBadge";

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
            <span className="slide-thumbnail">
              <small>{index + 1}</small>
              <strong>{item.title}</strong>
            </span>
            <span>Slide {index + 1}</span>
          </button>
        ))}
      </nav>
      <div className="slide-review">
        <div className="slide-canvas">
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
}: {
  artifact: ReviewArtifactRun;
  version: ReviewArtifactVersion | null;
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
}) {
  const [editContent, setEditContent] = useState(version?.content ?? "");
  const [editing, setEditing] = useState(false);
  const label = outputLabel(artifact.output_type);

  useEffect(() => {
    setEditContent(version?.content ?? "");
    setEditing(false);
  }, [artifact.artifact_run_id, version?.id, version?.content]);

  function beginEdit() {
    setEditContent(version?.content ?? "");
    setEditing(true);
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
          <p className="eyebrow">
            Source V{version?.source_version_number ?? "—"}
            {version && <span aria-hidden="true"> · </span>}
            {version ? "Version " + version.version_number : "No version yet"}
          </p>
          <h2 id="artifact-title">{label}</h2>
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
              className="button-secondary"
              onClick={onRegenerate}
              disabled={busy}
            >
              <RefreshCw aria-hidden="true" />
              Regenerate
            </button>
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
                      onClick={() => onReviewStatus("accepted")}
                      disabled={busy}
                    >
                      <Check aria-hidden="true" />
                      Accept
                    </button>
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
            <label htmlFor="artifact-editor">Edit {label}</label>
            <textarea
              id="artifact-editor"
              rows={18}
              value={editContent}
              onChange={(event) => setEditContent(event.target.value)}
            />
            <p className="field-hint">Saving creates a new version.</p>
            <div className="review-actions">
              <button
                type="button"
                className="button-primary"
                onClick={() => onSave(editContent)}
                disabled={busy}
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
        ) : artifact.output_type === "presentation" ? (
          <PresentationViewer content={version.content} />
        ) : (
          <article className="artifact-document">
            <div className="artifact-document__lineage">
              <span>Source</span>
              <span />
              <strong>{label}</strong>
              <span />
              <span>Evidence</span>
            </div>
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
    </section>
  );
}
