import { createPortal } from "react-dom";
import {
  FileCheck2,
  FileText,
  Megaphone,
  MessageCircle,
  Presentation,
} from "lucide-react";
import type { ReviewArtifactRun, OutputType } from "../types";
import { artifactStatus, outputLabel } from "../utils";

const OUTPUT_ICONS: Record<OutputType, typeof FileText> = {
  executive_summary: FileCheck2,
  linkedin_post: Megaphone,
  x_post: MessageCircle,
  advisory: FileText,
  presentation: Presentation,
};

export function ArtifactRail({
  artifacts,
  activeArtifactId,
  sourceVersion,
  onSourceSelect,
  onSelect,
}: {
  artifacts: ReviewArtifactRun[];
  activeArtifactId: number | null;
  sourceVersion: number;
  onSourceSelect: () => void;
  onSelect: (artifactRunId: number) => void;
}) {
  const target = document.getElementById("review-context-navigation");
  if (!target) return null;
  return createPortal(
    <nav className="review-sidebar-context" aria-label="Review navigation">
      <p className="sidebar-section-label">Source</p>
      <button type="button" className="sidebar-link" onClick={onSourceSelect}>
        <FileText aria-hidden="true" />
        <span>Source V{sourceVersion}</span>
      </button>
      {artifacts.length > 0 && (
        <p className="sidebar-section-label">Artifacts</p>
      )}
      <ul>
        {artifacts.map((artifact) => {
          const latest = artifact.versions.at(-1);
          const status = artifactStatus(
            artifact.status,
            latest?.review_status ?? null,
          );
          const Icon = OUTPUT_ICONS[artifact.output_type];
          return (
            <li key={artifact.artifact_run_id}>
              <button
                type="button"
                className={
                  "sidebar-link review-sidebar-context__item" +
                  (artifact.artifact_run_id === activeArtifactId
                    ? " is-active"
                    : "")
                }
                aria-current={
                  artifact.artifact_run_id === activeArtifactId
                    ? "page"
                    : undefined
                }
                aria-label={outputLabel(artifact.output_type)}
                onClick={() => onSelect(artifact.artifact_run_id)}
              >
                <span className="review-sidebar-context__label">
                  <Icon aria-hidden="true" />
                  <span>{outputLabel(artifact.output_type)}</span>
                </span>
                {latest && (
                  <span
                    className="review-sidebar-context__dot"
                    aria-hidden="true"
                    title={status}
                  />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>,
    target,
  );
}
