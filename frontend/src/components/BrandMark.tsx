export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={compact ? "brand-mark brand-mark--compact" : "brand-mark"}>
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <path d="M7 9.5h9.5c7 0 7 17 14 17H29" />
        <path d="M7 18h9.5c7 0 7-8.5 14-8.5H29" />
        <path d="M7 26.5h9.5c7 0 7-8.5 14-8.5H29" />
        <circle cx="7" cy="9.5" r="2.4" />
        <circle cx="7" cy="18" r="2.4" />
        <circle cx="7" cy="26.5" r="2.4" />
        <circle cx="29" cy="9.5" r="2.4" />
        <circle cx="29" cy="18" r="2.4" />
        <circle cx="29" cy="26.5" r="2.4" />
      </svg>
      {!compact && <span className="brand-mark__word">AxiomWeave</span>}
    </span>
  );
}
