import { ArrowRight, FileText } from "lucide-react";

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <section className="empty-state" aria-labelledby="empty-state-title">
      <div className="empty-weave" aria-hidden="true">
        <div className="empty-weave__source">
          <FileText />
          <span>Source</span>
        </div>
        <span className="empty-weave__line" />
        <div className="empty-weave__artifacts">
          <span>Summary</span>
          <span>Post</span>
          <span>Advisory</span>
          <span>Slides</span>
        </div>
      </div>
      <div className="empty-state__copy">
        <p className="eyebrow">A clear place to begin</p>
        <h2 id="empty-state-title">{title}</h2>
        <p>{description}</p>
        <button type="button" onClick={onAction}>
          {actionLabel}
          <ArrowRight aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
