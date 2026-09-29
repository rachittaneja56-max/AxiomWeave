import { useEffect, useMemo, useRef } from "react";
import { X } from "lucide-react";
import type { SourceVersionContent } from "../types";

export function SourceViewerDialog({
  source,
  quote,
  onClose,
}: {
  source: SourceVersionContent;
  quote?: string | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const markRef = useRef<HTMLElement>(null);
  const match = useMemo(() => {
    if (!quote) return -1;
    return source.source_text.indexOf(quote);
  }, [quote, source.source_text]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    if (match >= 0 && typeof markRef.current?.scrollIntoView === "function") {
      markRef.current.scrollIntoView({ block: "center" });
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const items = dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (!items?.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      previous?.focus();
    };
  }, [match, onClose]);

  const text = source.source_text;
  return (
    <div
      className="dialog-scrim source-viewer-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="source-viewer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-viewer-title"
        tabIndex={-1}
        ref={dialogRef}
      >
        <header className="source-viewer__header">
          <div>
            <p className="eyebrow">Current source</p>
            <h2 id="source-viewer-title">Source V{source.version_number}</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Close source viewer"
            onClick={onClose}
          >
            <X aria-hidden="true" />
          </button>
        </header>
        <div className="source-viewer__body" tabIndex={0}>
          {match >= 0 && quote ? (
            <>
              {text.slice(0, match)}
              <mark ref={markRef} className="source-viewer__highlight">
                {text.slice(match, match + quote.length)}
              </mark>
              {text.slice(match + quote.length)}
            </>
          ) : (
            text
          )}
        </div>
      </section>
    </div>
  );
}
