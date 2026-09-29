import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import {
  deriveTransformationTitle,
  isDashboardItem,
  relativeDate,
  transformationStatus,
} from "../utils";
import type { DashboardItem } from "../types";

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
          </div>
          <div className="transformation-list">
            {rows.map(({ item, title }) => (
              <button
                type="button"
                className="transformation-card"
                key={item.transformation_run_id}
                aria-label={title}
                onClick={() =>
                  onOpenReview(
                    item.transformation_run_id,
                    title,
                    item.source_version.version_number,
                  )
                }
              >
                <div className="transformation-card__main">
                  <div className="transformation-card__heading">
                    <div>
                      <h2 className="card-title">{title}</h2>
                      <p className="card-kicker">
                        Source V{item.source_version.version_number}
                        <span aria-hidden="true"> � </span>
                        Updated {relativeDate(item.updated_at)}
                        <span aria-hidden="true"> � </span>
                        {
                          item.artifact_states.filter(
                            (artifact) => artifact.status !== null,
                          ).length
                        }{" "}
                        artifact
                        {item.artifact_states.filter(
                          (artifact) => artifact.status !== null,
                        ).length === 1
                          ? ""
                          : "s"}
                      </p>
                    </div>
                    <StatusBadge status={transformationStatus(item)} />
                  </div>
                </div>
                <span className="transformation-card__open" aria-hidden="true">
                  <ArrowRight aria-hidden="true" />
                </span>
              </button>
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
