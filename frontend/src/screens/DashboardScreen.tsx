import { useEffect, useState } from "react";
import {
  ArrowRight,
  FileCheck2,
  FileText,
  Megaphone,
  Presentation,
  RefreshCw,
} from "lucide-react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import {
  artifactStatus,
  deriveTransformationTitle,
  isDashboardItem,
  relativeDate,
  transformationStatus,
} from "../utils";
import { OUTPUT_TYPES, type DashboardItem, type OutputType } from "../types";

const OUTPUT_ICONS: Record<OutputType, typeof FileText> = {
  executive_summary: FileCheck2,
  linkedin_post: Megaphone,
  advisory: FileText,
  presentation: Presentation,
};

type DashboardRow = {
  item: DashboardItem;
  title: string;
};

export function DashboardScreen({
  onCreate,
  onOpenReview,
}: {
  onCreate: () => void;
  onOpenReview: (id: number, title: string, sourceVersion: number) => void;
}) {
  const [rows, setRows] = useState<DashboardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const body = await api.transformations();
        if (!Array.isArray(body) || !body.every(isDashboardItem)) {
          throw new Error("Unexpected transformation list.");
        }
        const items = body as DashboardItem[];
        const nextRows = await Promise.all(
          items.map(async (item) => {
            try {
              const source = await api.sourceVersion(item.source_version.id);
              if (
                typeof source === "object" &&
                source !== null &&
                "source_text" in source &&
                typeof source.source_text === "string"
              ) {
                return {
                  item,
                  title: deriveTransformationTitle(source.source_text),
                };
              }
            } catch {
              // The readable title is a convenience. Keep the transformation
              // available if an individual source preview cannot be loaded.
            }
            return { item, title: "Untitled transformation" };
          }),
        );
        if (active) setRows(nextRows);
      } catch {
        if (active) {
          setError("Could not load your transformations. Please retry.");
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [reload]);

  return (
    <section className="dashboard-screen" aria-label="Saved transformations">
      {loading ? (
        <div className="dashboard-skeletons" role="status">
          <span>Loading your transformations…</span>
          <div />
          <div />
        </div>
      ) : error ? (
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="button-secondary"
            onClick={() => setReload((value) => value + 1)}
          >
            <RefreshCw aria-hidden="true" />
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title="Create your first transformation"
          description="Start with a source you trust. Shape it into useful materials, then review how each claim connects back."
          actionLabel="New transformation"
          onAction={onCreate}
        />
      ) : (
        <>
          <div className="dashboard-overview">
            <div>
              <p className="eyebrow">Your work</p>
              <h2>
                {rows.length} transformation{rows.length === 1 ? "" : "s"}
              </h2>
            </div>
            <div className="dashboard-overview__key">
              <span className="legend-dot legend-dot--ready" />
              <span>Artifacts ready to review</span>
            </div>
          </div>
          <div className="transformation-list">
            {rows.map(({ item, title }) => (
              <article
                className="transformation-card"
                key={item.transformation_run_id}
              >
                <div className="transformation-card__main">
                  <div className="transformation-card__heading">
                    <div>
                      <p className="card-kicker">
                        Source V{item.source_version.version_number}
                        <span aria-hidden="true"> · </span>
                        Updated {relativeDate(item.updated_at)}
                      </p>
                      <h2>
                        <button
                          type="button"
                          className="card-title-button"
                          onClick={() =>
                            onOpenReview(
                              item.transformation_run_id,
                              title,
                              item.source_version.version_number,
                            )
                          }
                        >
                          <span>{title}</span>
                          <ArrowRight aria-hidden="true" />
                        </button>
                      </h2>
                    </div>
                    <StatusBadge status={transformationStatus(item)} />
                  </div>
                  <div
                    className="artifact-indicators"
                    aria-label="Artifact status"
                  >
                    {OUTPUT_TYPES.map((output) => {
                      const state = item.artifact_states.find(
                        (artifact) => artifact.output_type === output.value,
                      );
                      const status = artifactStatus(
                        state?.status ?? null,
                        state?.review_status ?? null,
                      );
                      const Icon = OUTPUT_ICONS[output.value];
                      return (
                        <span
                          className={
                            "artifact-indicator artifact-indicator--" +
                            status.toLowerCase().replaceAll(" ", "-")
                          }
                          key={output.value}
                          title={output.label + ": " + status}
                        >
                          <Icon aria-hidden="true" />
                          <span>{output.shortLabel}</span>
                          <span className="artifact-indicator__status">
                            {status}
                          </span>
                        </span>
                      );
                    })}
                  </div>
                </div>
                <button
                  type="button"
                  className="transformation-card__open"
                  onClick={() =>
                    onOpenReview(
                      item.transformation_run_id,
                      title,
                      item.source_version.version_number,
                    )
                  }
                >
                  Open review
                  <ArrowRight aria-hidden="true" />
                </button>
              </article>
            ))}
          </div>
          <button type="button" className="dashboard-more" onClick={onCreate}>
            Create another transformation
            <ArrowRight aria-hidden="true" />
          </button>
        </>
      )}
    </section>
  );
}
