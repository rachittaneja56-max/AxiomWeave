import { FileCheck2, FileText, Megaphone, Presentation } from "lucide-react";
import type { ReviewArtifactRun, OutputType } from "../types";
import { artifactStatus, outputLabel } from "../utils";
import { StatusBadge } from "../components/StatusBadge";

const OUTPUT_ICONS: Record<OutputType, typeof FileText> = {
  executive_summary: FileCheck2,
  linkedin_post: Megaphone,
  advisory: FileText,
  presentation: Presentation,
};

export function ArtifactRail({
  artifacts,
  activeArtifactId,
  onSelect,
}: {
  artifacts: ReviewArtifactRun[];
  activeArtifactId: number | null;
  onSelect: (artifactRunId: number) => void;
}) {
  return (
    <nav className="artifact-rail" aria-label="Artifacts">
      <div className="artifact-rail__heading">
        <p className="eyebrow">Your output</p>
        <h2>Artifacts</h2>
      </div>
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
                  "artifact-rail__item" +
                  (artifact.artifact_run_id === activeArtifactId
                    ? " is-active"
                    : "")
                }
                aria-current={
                  artifact.artifact_run_id === activeArtifactId
                    ? "page"
                    : undefined
                }
                onClick={() => onSelect(artifact.artifact_run_id)}
              >
                <span className="artifact-rail__icon">
                  <Icon aria-hidden="true" />
                </span>
                <span className="artifact-rail__copy">
                  <strong>{outputLabel(artifact.output_type)}</strong>
                  <small>
                    {latest ? "Version " + latest.version_number : status}
                  </small>
                </span>
                <span
                  className={
                    "artifact-rail__status artifact-rail__status--" +
                    status.toLowerCase().replaceAll(" ", "-")
                  }
                  aria-label={status}
                  title={status}
                />
              </button>
            </li>
          );
        })}
      </ul>
      <div className="artifact-rail__key">
        <StatusBadge status="Ready for review" compact />
        <p>Choose an artifact to review its content and source support.</p>
      </div>
    </nav>
  );
}
