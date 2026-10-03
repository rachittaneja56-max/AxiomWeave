import {
  AlertTriangle,
  BookOpenCheck,
  Clock3,
  Info,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import type {
  DiscrepancyFinding,
  EvidenceLink,
  InspectorTab,
  ReviewArtifactRun,
  ReviewArtifactVersion,
  SourceVersion,
  TransformationDetail,
} from "../types";
type WarningItem = {
  finding: DiscrepancyFinding;
  labelA: string;
  labelB: string;
};

function EvidencePanel({
  version,
  evidence,
  busy,
  onLoad,
  onAnalyze,
  onResumeClaimScan,
  onViewSource,
}: {
  version: ReviewArtifactVersion | null;
  evidence: EvidenceLink[] | undefined;
  busy: boolean;
  onLoad: () => void;
  onAnalyze: () => void;
  onResumeClaimScan: (scanId: number) => void;
  onViewSource: (sourceVersionId: number, quote: string | null) => void;
}) {
  if (!version) {
    return (
      <div className="inspector-empty">
        <BookOpenCheck aria-hidden="true" />
        <p>Evidence appears when an artifact version is available.</p>
      </div>
    );
  }
  return (
    <div className="inspector-panel-content">
      <div className="inspector-panel-intro">
        <span className="inspector-panel-icon inspector-panel-icon--evidence">
          <ShieldCheck aria-hidden="true" />
        </span>
        <div>
          <h3>Source support</h3>
          <p>Review the passages linked to this artifact’s claims.</p>
        </div>
      </div>
      <div className="context-coverage" aria-label="Context and claim coverage">
        <section>
          <strong>Context used</strong>
          {version.context_manifest ? (
            <>
              <p>
                {version.context_manifest.route === "R0_FULL_CONTEXT"
                  ? "Full source context (R0)"
                  : "Retrieved candidate (R1)"}
                {" · Pack V"}
                {version.context_manifest.source_pack_version_id}
                {" · "}
                {version.context_manifest.region_count} regions
              </p>
              <p>
                {version.context_manifest.extraction_coverage === "partial"
                  ? "Partial extraction"
                  : "Extraction marked complete"}
                {" · "}
                {version.context_manifest.estimated_context_units.toLocaleString()}
                {" / "}
                {version.context_manifest.context_budget_units.toLocaleString()}
                {" character units"}
              </p>
              {version.context_manifest.warnings.length > 0 && (
                <p className="context-coverage__warning">
                  Context warning:{" "}
                  {version.context_manifest.warnings.join(", ")}
                </p>
              )}
            </>
          ) : (
            <p>No context manifest was stored for this historical version.</p>
          )}
        </section>
        <section>
          <strong>Claim coverage</strong>
          {version.claim_scan ? (
            <>
              <p>
                {version.claim_scan.status === "complete"
                  ? "Complete"
                  : version.claim_scan.status === "running"
                    ? "In progress"
                    : "Needs review"}
                {" · "}
                {version.claim_scan.completed_batches.toLocaleString()}
                {" / "}
                {version.claim_scan.total_batches.toLocaleString()}
                {" batches · "}
                {version.claim_scan.claims_found.toLocaleString()}
                {" material claims"}
              </p>
              {version.claim_scan.status !== "complete" && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onResumeClaimScan(version.claim_scan!.id)}
                  disabled={busy}
                >
                  Retry incomplete batches
                </button>
              )}
            </>
          ) : (
            <p>No material-claim scan has been run for this version.</p>
          )}
        </section>
      </div>
      <div className="inspector-actions">
        <button
          type="button"
          className="button-primary button-primary--small"
          onClick={onAnalyze}
          disabled={busy}
        >
          {busy ? <LoaderCircle className="status-spin" /> : <ShieldCheck />}
          Analyze claims
        </button>
        <button
          type="button"
          className="text-button"
          onClick={onLoad}
          disabled={busy}
        >
          View saved evidence
        </button>
      </div>
      {evidence === undefined ? (
        <div className="inspector-note">
          <Info aria-hidden="true" />
          <p>Saved source support has not been loaded for this version.</p>
        </div>
      ) : evidence.length === 0 ? (
        <div className="inspector-note">
          <Info aria-hidden="true" />
          <p>No saved evidence claims were found for this version.</p>
        </div>
      ) : (
        <ul className="evidence-list">
          {evidence.map((link) => {
            const quote = link.source_quote ?? "";
            return (
              <li key={link.id} className="evidence-item">
                <strong className="evidence-item__claim">
                  {link.claim_text}
                </strong>
                {link.status === "linked" ? (
                  <>
                    <span className="evidence-status evidence-status--linked">
                      Quote located in Source V{version.source_version_number}
                    </span>
                    {quote && (
                      <blockquote className="evidence-quote">
                        {quote}
                      </blockquote>
                    )}
                    {link.source_locator && (
                      <p className="evidence-locator">{link.source_locator}</p>
                    )}
                    <button
                      type="button"
                      className="text-button evidence-view-source"
                      onClick={() =>
                        onViewSource(link.source_version_id, link.source_quote)
                      }
                    >
                      View in source
                    </button>
                  </>
                ) : (
                  <div className="evidence-status evidence-status--unlocated">
                    <AlertTriangle aria-hidden="true" />
                    <span>
                      <strong>Source support not located</strong>
                      <small>
                        No exact quotation was located for this claim.
                      </small>
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <p className="inspector-disclaimer">
        A linked quotation shows where the wording appears. It does not confirm
        that a claim is complete or correct.
      </p>
    </div>
  );
}

function WarningsPanel({
  warnings,
  checked,
  partialWarnings,
  checking,
  busy,
  onCheck,
  onDismiss,
}: {
  warnings: WarningItem[];
  checked: boolean;
  partialWarnings: boolean;
  checking: boolean;
  busy: boolean;
  onCheck: () => void;
  onDismiss: (finding: DiscrepancyFinding) => void;
}) {
  return (
    <div className="inspector-panel-content">
      <div className="inspector-panel-intro">
        <span className="inspector-panel-icon inspector-panel-icon--warning">
          <AlertTriangle aria-hidden="true" />
        </span>
        <div>
          <h3>Sibling consistency</h3>
          <p>Compare selected artifacts for statements that may differ.</p>
        </div>
      </div>
      <button
        type="button"
        className="button-primary button-primary--small warning-check"
        onClick={onCheck}
        disabled={busy || checking}
      >
        {checking ? (
          <LoaderCircle className="status-spin" aria-hidden="true" />
        ) : (
          <AlertTriangle aria-hidden="true" />
        )}
        {checking ? "Checking artifacts…" : "Check sibling consistency"}
      </button>
      {partialWarnings && (
        <p className="notice" role="status">
          Some sibling comparisons could not be completed. Successful
          comparisons are shown below. Retry the remaining checks.
        </p>
      )}
      {!checked ? (
        <div className="inspector-note">
          <Info aria-hidden="true" />
          <p>This review runs only when you ask it to.</p>
        </div>
      ) : warnings.length === 0 ? (
        <div className="inspector-note inspector-note--success">
          <ShieldCheck aria-hidden="true" />
          <p>No possible discrepancies were found in this check.</p>
        </div>
      ) : (
        <div className="warning-list">
          {warnings.map(({ finding, labelA, labelB }) => (
            <article className="warning-card" key={finding.id}>
              <div className="warning-card__heading">
                <span className="warning-icon">
                  <AlertTriangle aria-hidden="true" />
                </span>
                <div>
                  <strong>Possible discrepancy</strong>
                  <small>
                    {labelA} · {labelB}
                  </small>
                </div>
              </div>
              <p>{finding.explanation}</p>
              <dl>
                <div>
                  <dt>{labelA}</dt>
                  <dd>{finding.statement_a}</dd>
                </div>
                <div>
                  <dt>{labelB}</dt>
                  <dd>{finding.statement_b}</dd>
                </div>
              </dl>
              {finding.review_status === "open" ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onDismiss(finding)}
                  disabled={busy}
                >
                  Dismiss warning
                </button>
              ) : (
                <span className="warning-dismissed">Dismissed</span>
              )}
            </article>
          ))}
        </div>
      )}
      <p className="inspector-disclaimer">
        These are review prompts. They do not select a correct artifact or
        rewrite content.
      </p>
    </div>
  );
}

function VersionsPanel({
  artifact,
  selectedVersionId,
  onSelect,
}: {
  artifact: ReviewArtifactRun | null;
  selectedVersionId: number | null;
  onSelect: (versionId: number) => void;
}) {
  if (!artifact?.versions.length) {
    return (
      <div className="inspector-empty">
        <Clock3 aria-hidden="true" />
        <p>Versions appear after this artifact is created or edited.</p>
      </div>
    );
  }
  const versions = [...artifact.versions].sort(
    (left, right) => right.version_number - left.version_number,
  );
  return (
    <div className="inspector-panel-content">
      <div className="inspector-panel-intro">
        <span className="inspector-panel-icon inspector-panel-icon--version">
          <Clock3 aria-hidden="true" />
        </span>
        <div>
          <h3>Version history</h3>
          <p>Select a version to read that saved artifact.</p>
        </div>
      </div>
      <ol className="version-timeline">
        {versions.map((version, index) => (
          <li
            key={version.id}
            className={version.id === selectedVersionId ? "is-selected" : ""}
          >
            <span className="version-timeline__node" aria-hidden="true" />
            <button
              type="button"
              className="version-timeline__button"
              aria-current={
                version.id === selectedVersionId ? "true" : undefined
              }
              onClick={() => onSelect(version.id)}
            >
              <span className="version-timeline__title">
                Version {version.version_number}
                {index === 0 && <small>Current</small>}
              </span>
              <span className="version-timeline__meta">
                Source V{version.source_version_number} ·{" "}
                {version.review_status === "draft"
                  ? "Ready for review"
                  : version.review_status[0].toUpperCase() +
                    version.review_status.slice(1)}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function DetailsPanel({
  detail,
  sourceVersion,
  version,
}: {
  detail: TransformationDetail;
  sourceVersion: SourceVersion;
  version: ReviewArtifactVersion | null;
}) {
  const controlLabels: Record<string, string> = {
    audience: "Audience",
    tone: "Tone",
    language: "Language",
    detail_level: "Detail",
    objective: "Objective",
    style: "Style",
    supporting_context: "Supporting context",
  };
  return (
    <div className="inspector-panel-content">
      <div className="inspector-panel-intro">
        <span className="inspector-panel-icon inspector-panel-icon--details">
          <Info aria-hidden="true" />
        </span>
        <div>
          <h3>Transformation details</h3>
          <p>Source and writing settings used for this work.</p>
        </div>
      </div>
      <dl className="detail-list">
        {Object.entries(detail.controls)
          .filter(([, value]) => Boolean(value))
          .map(([key, value]) => (
            <div key={key}>
              <dt>{controlLabels[key] ?? key.replaceAll("_", " ")}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      <div className="provenance-summary">
        <div>
          <span>Source</span>
          <strong>V{sourceVersion.version_number}</strong>
        </div>
        {version && (
          <div>
            <span>Artifact</span>
            <strong>V{version.version_number}</strong>
          </div>
        )}
        {version?.created_at && (
          <div>
            <span>Created</span>
            <strong>
              {new Intl.DateTimeFormat(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              }).format(Date.parse(version.created_at))}
            </strong>
          </div>
        )}
      </div>
      {version && (
        <details className="technical-provenance">
          <summary>Technical provenance</summary>
          <dl>
            {version.provider && (
              <div>
                <dt>Provider</dt>
                <dd>{version.provider}</dd>
              </div>
            )}
            {version.model && (
              <div>
                <dt>Model</dt>
                <dd>{version.model}</dd>
              </div>
            )}
            {version.prompt_version && (
              <div>
                <dt>Prompt version</dt>
                <dd>{version.prompt_version}</dd>
              </div>
            )}
            {version.prompt_hash && (
              <div className="provenance-hash">
                <dt>Prompt fingerprint</dt>
                <dd>{version.prompt_hash}</dd>
              </div>
            )}
          </dl>
        </details>
      )}
    </div>
  );
}

const TABS: { id: InspectorTab; label: string; icon: typeof ShieldCheck }[] = [
  { id: "evidence", label: "Evidence", icon: ShieldCheck },
  { id: "warnings", label: "Warnings", icon: AlertTriangle },
  { id: "versions", label: "Versions", icon: Clock3 },
  { id: "details", label: "Details", icon: Info },
];

export function InspectorPanel({
  activeTab,
  onTabChange,
  detail,
  sourceVersion,
  artifact,
  version,
  selectedVersionId,
  evidence,
  warnings,
  warningsChecked,
  partialWarnings,
  checkingWarnings,
  busy,
  onLoadEvidence,
  onAnalyzeEvidence,
  onResumeClaimScan,
  onViewSource,
  onCheckWarnings,
  onDismissWarning,
  onSelectVersion,
}: {
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  detail: TransformationDetail;
  sourceVersion: SourceVersion;
  artifact: ReviewArtifactRun | null;
  version: ReviewArtifactVersion | null;
  selectedVersionId: number | null;
  evidence: EvidenceLink[] | undefined;
  warnings: WarningItem[];
  warningsChecked: boolean;
  partialWarnings: boolean;
  checkingWarnings: boolean;
  busy: boolean;
  onLoadEvidence: () => void;
  onAnalyzeEvidence: () => void;
  onResumeClaimScan: (scanId: number) => void;
  onViewSource: (sourceVersionId: number, quote: string | null) => void;
  onCheckWarnings: () => void;
  onDismissWarning: (finding: DiscrepancyFinding) => void;
  onSelectVersion: (versionId: number) => void;
}) {
  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentIndex = TABS.findIndex((tab) => tab.id === activeTab);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = TABS[(currentIndex + step + TABS.length) % TABS.length];
    onTabChange(next.id);
    const buttons =
      event.currentTarget.parentElement?.querySelectorAll('[role="tab"]');
    (
      buttons?.[TABS.findIndex((tab) => tab.id === next.id)] as
        HTMLElement | undefined
    )?.focus();
  }

  return (
    <aside className="review-inspector" aria-label="Review inspector">
      <div className="inspector-heading">
        <div>
          <p className="eyebrow">Traceability</p>
          <h2>Traceability</h2>
        </div>
        <span className="inspector-source-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </div>
      <div
        className="inspector-tabs"
        role="tablist"
        aria-label="Review details"
      >
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            type="button"
            role="tab"
            key={id}
            aria-selected={activeTab === id}
            aria-controls={"inspector-panel-" + id}
            id={"inspector-tab-" + id}
            tabIndex={activeTab === id ? 0 : -1}
            className={activeTab === id ? "is-active" : ""}
            onClick={() => onTabChange(id)}
            onKeyDown={handleTabKeyDown}
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>
      <div
        className="inspector-body"
        role="tabpanel"
        id={"inspector-panel-" + activeTab}
        aria-labelledby={"inspector-tab-" + activeTab}
        tabIndex={0}
      >
        {activeTab === "evidence" && (
          <EvidencePanel
            version={version}
            evidence={evidence}
            busy={busy}
            onLoad={onLoadEvidence}
            onAnalyze={onAnalyzeEvidence}
            onResumeClaimScan={onResumeClaimScan}
            onViewSource={onViewSource}
          />
        )}
        {activeTab === "warnings" && (
          <WarningsPanel
            warnings={warnings}
            checked={warningsChecked}
            partialWarnings={partialWarnings}
            checking={checkingWarnings}
            busy={busy}
            onCheck={onCheckWarnings}
            onDismiss={onDismissWarning}
          />
        )}
        {activeTab === "versions" && (
          <VersionsPanel
            artifact={artifact}
            selectedVersionId={selectedVersionId}
            onSelect={onSelectVersion}
          />
        )}
        {activeTab === "details" && (
          <DetailsPanel
            detail={detail}
            sourceVersion={sourceVersion}
            version={version}
          />
        )}
      </div>
    </aside>
  );
}
