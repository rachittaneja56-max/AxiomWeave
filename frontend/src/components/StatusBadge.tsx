import {
  Check,
  CircleAlert,
  Clock3,
  FileClock,
  LoaderCircle,
} from "lucide-react";

const STATUS_CLASS: Record<string, string> = {
  "Ready for review": "status--review",
  "Needs attention": "status--warning",
  Generating: "status--progress",
  Complete: "status--complete",
  Accepted: "status--complete",
  Rejected: "status--muted",
  Draft: "status--muted",
  Ready: "status--review",
  Waiting: "status--muted",
  "Not selected": "status--quiet",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "Accepted" || status === "Complete") {
    return <Check aria-hidden="true" />;
  }
  if (status === "Needs attention") {
    return <CircleAlert aria-hidden="true" />;
  }
  if (status === "Generating") {
    return <LoaderCircle className="status-spin" aria-hidden="true" />;
  }
  if (status === "Waiting") {
    return <Clock3 aria-hidden="true" />;
  }
  return <FileClock aria-hidden="true" />;
}

export function StatusBadge({
  status,
  compact = false,
}: {
  status: string;
  compact?: boolean;
}) {
  return (
    <span
      className={
        "status-badge " +
        (STATUS_CLASS[status] ?? "status--quiet") +
        (compact ? " status-badge--compact" : "")
      }
    >
      <StatusIcon status={status} />
      <span>{status}</span>
    </span>
  );
}
