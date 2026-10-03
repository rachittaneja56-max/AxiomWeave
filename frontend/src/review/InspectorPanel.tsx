import { useState } from "react";
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
  ArtifactLineage,
  EvidenceState,
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
  lineage,
  busy,
  onLoad,
  onAnalyze,
  onVerify,
  onReviewEvidence,
  onResumeClaimScan,
  onViewSource,
}: {
  version: ReviewArtifactVersion | null;
  evidence: EvidenceLink[] | undefined;
  lineage: ArtifactLineage | undefined;
  busy: boolean;
  onLoad: () => void;
  onAnalyze: () => void;
  onVerify: () => void;
  onReviewEvidence: (assessmentId: number, state: EvidenceState) => void;
  onResumeClaimScan: (scanId: number) => void;
  onViewSource: (sourceVersionId: number, quote: string | null) => void;
}) {
  const [adjudicatedStates, setAdjudicatedStates] = useState<
    Record<number, EvidenceState>
  >({});
  if (!version) {
    return (
      <div className="inspector-empty">
        <BookOpenCheck aria-hidden="true" />
        <p>Evidence appears when an artifact version is available.</p>
      </div>
    );
  }

  const scan = version.claim_scan;
  const scanComplete = scan?.status === "complete";
  const scanRunning = scan?.status === "pending" || scan?.status === "running";
  const lineageClaims = lineage?.claims ?? [];
  const claims = lineageClaims.length
    ? lineageClaims
    : (evidence ?? []).map((link, index) => ({
        id: Number.MIN_SAFE_INTEGER + index,
        proposition: link.claim_text,
        artifact_quote: link.claim_text,
        block_mapping_state: null,
        block_keys: [],
      }));
  const assessments = lineage?.assessments ?? [];

  function evidenceForClaim(
    claimId: number,
    proposition: string,
    quote: string,
  ) {
    const assessment = assessments.find(
      (item) => item.material_claim_id === claimId,
    );
    const evidenceLink = evidence?.find(
      (item) =>
        item.claim_text.trim() === proposition.trim() ||
        item.claim_text.trim() === quote.trim(),
    );
    const sourceQuote = assessment?.source_quote ?? evidenceLink?.source_quote;
    const state: EvidenceState | null =
      assessment?.adjudicated_state ??
      assessment?.evidence_state ??
      (evidenceLink?.status === "linked"
        ? "quote_located"
        : evidenceLink?.status === "support_not_located"
          ? "missing"
          : null);
    return { assessment, evidenceLink, sourceQuote, state };
  }

  return (
    <div className="inspector-panel-content">
      <div className="inspector-panel-intro">
        <span className="inspector-panel-icon inspector-panel-icon--evidence">
          <ShieldCheck aria-hidden="true" />
        </span>
        <div>
          <h3>Evidence</h3>
          <p>See the artifact’s factual claims and their source support.</p>
        </div>
      </div>

      {version.context_manifest && (
        <section className="source-context-summary">
          <strong>Full source context</strong>
          <p>
            Source V{version.source_version_number} ·{" "}
            {version.context_manifest.region_count} regions
            {version.context_manifest.extraction_coverage === "partial" &&
              " · Partial extraction"}
          </p>
          {version.context_manifest.warnings.length > 0 && (
            <p className="context-coverage__warning">
              Context warning: {version.context_manifest.warnings.join(", ")}
            </p>
          )}
          <details>
            <summary>Context details</summary>
            <p>
              Route: {version.context_manifest.route} · Pack V
              {version.context_manifest.source_pack_version_id}
            </p>
            <p>
              {version.context_manifest.estimated_context_units.toLocaleString()}{" "}
              / {version.context_manifest.context_budget_units.toLocaleString()}{" "}
              character units
            </p>
          </details>
        </section>
      )}

      {!scanComplete ? (
        <section className="claim-analysis-state" aria-live="polite">
          {scanRunning ? (
            <>
              <p className="claim-analysis-state__status">
                <LoaderCircle className="status-spin" aria-hidden="true" />
                Analyzing claims…
              </p>
              <p>
                {scan?.completed_batches ?? 0} / {scan?.total_batches ?? 0}{" "}
                batches complete
              </p>
            </>
          ) : (
            <>
              <h4>Claim analysis has not been completed for this version.</h4>
              <p>
                Analyze the artifact to identify factual claims and connect them
                to source support.
              </p>
            </>
          )}
          {lineage?.blocks.length ? (
            <p className="claim-analysis-state__secondary">
              {lineage.blocks.length} content blocks prepared for lineage.
            </p>
          ) : null}
          {!scanRunning && (
            <button
              type="button"
              className="button-primary button-primary--small"
              onClick={onAnalyze}
              disabled={busy}
            >
              {busy ? (
                <LoaderCircle className="status-spin" />
              ) : (
                <ShieldCheck />
              )}
              Analyze claims
            </button>
          )}
          {scan && !scanRunning && scan.status !== "complete" && (
            <button
              type="button"
              className="text-button"
              onClick={() => onResumeClaimScan(scan.id)}
              disabled={busy}
            >
              Retry incomplete batches
            </button>
          )}
        </section>
      ) : (
        <>
          <section className="claim-analysis-summary">
            <h4>Claim analysis</h4>
            <p>
              Complete · {claims.length.toLocaleString()}{" "}
              {claims.length === 1 ? "claim" : "claims"}
            </p>
          </section>
          {claims.length ? (
            <section
              className="claim-cards"
              aria-label="Claims and source support"
            >
              <h4>Claims and source support</h4>
              {claims.map((claim) => {
                const trace = evidenceForClaim(
                  claim.id,
                  claim.proposition,
                  claim.artifact_quote,
                );
                const selectedState = trace.state;
                const statusLabel = selectedState
                  ? evidenceStateLabel(selectedState)
                  : "Not assessed";
                const assessment = trace.assessment;
                return (
                  <article className="claim-card" key={claim.id}>
                    <span className="claim-card__eyebrow">Claim</span>
                    <strong className="claim-card__text">
                      {claim.proposition}
                    </strong>
                    <span
                      className={`evidence-chip${selectedState ? ` evidence-chip--${selectedState}` : ""}`}
                    >
                      {statusLabel}
                    </span>
                    {assessment && (
                      <dl className="claim-card__metadata">
                        <div>
                          <dt>Method</dt>
                          <dd>
                            {assessmentMethodLabel(
                              assessment.assessment_method,
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt>Review</dt>
                          <dd>
                            {assessment.review_state === "needs_review"
                              ? "Needs human review"
                              : "Reviewed"}
                          </dd>
                        </div>
                      </dl>
                    )}
                    {trace.sourceQuote ? (
                      <>
                        <div className="claim-card__source">
                          <span>Source V{version.source_version_number}</span>
                          <blockquote>{trace.sourceQuote}</blockquote>
                        </div>
                        <button
                          type="button"
                          className="text-button evidence-view-source"
                          onClick={() =>
                            onViewSource(
                              trace.evidenceLink?.source_version_id ??
                                version.source_version_id,
                              trace.sourceQuote ?? null,
                            )
                          }
                        >
                          Show in source
                        </button>
                      </>
                    ) : (
                      <p className="claim-card__source-missing">
                        Source quote not available
                      </p>
                    )}
                    {assessment?.review_state === "needs_review" && (
                      <div className="evidence-assessment-review">
                        <label>
                          Human assessment
                          <select
                            value={
                              adjudicatedStates[assessment.id] ??
                              assessment.adjudicated_state ??
                              assessment.evidence_state
                            }
                            onChange={(event) =>
                              setAdjudicatedStates((current) => ({
                                ...current,
                                [assessment.id]: event.target
                                  .value as EvidenceState,
                              }))
                            }
                          >
                            {(
                              [
                                "quote_located",
                                "supported",
                                "partial",
                                "contradicted",
                                "missing",
                                "ambiguous",
                                "conflict",
                                "non_factual",
                              ] as EvidenceState[]
                            ).map((state) => (
                              <option key={state} value={state}>
                                {evidenceStateLabel(state)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            onReviewEvidence(
                              assessment.id,
                              adjudicatedStates[assessment.id] ??
                                assessment.adjudicated_state ??
                                assessment.evidence_state,
                            )
                          }
                        >
                          Record human review
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </section>
          ) : (
            <p className="inspector-note">
              <Info aria-hidden="true" />
              <span>No material claims were found for this version.</span>
            </p>
          )}
          {claims.length > 0 && (
            <div className="inspector-actions">
              <button
                type="button"
                className="text-button"
                onClick={onAnalyze}
                disabled={busy}
              >
                Analyze claims
              </button>
              <button
                type="button"
                className="button-secondary button-primary--small"
                onClick={onVerify}
                disabled={busy}
              >
                <ShieldCheck aria-hidden="true" />
                Assess evidence
              </button>
              {evidence === undefined && (
                <button
                  type="button"
                  className="text-button"
                  onClick={onLoad}
                  disabled={busy}
                >
                  Load saved source support
                </button>
              )}
            </div>
          )}
        </>
      )}

      {lineage?.lineage_available && (
        <details className="technical-lineage">
          <summary>Technical lineage</summary>
          <p>
            {lineage.blocks.length} content blocks · {claims.length} material
            claims
          </p>
          <ul>
            {lineage.blocks.map((block) => (
              <li key={block.id}>
                <strong>{humanBlockLabel(block.block_key)}</strong>
                <code>{block.block_key}</code>
                <p>{block.visible_text}</p>
                <small>
                  {block.material_claim_ids.length} claims ·{" "}
                  {block.dependencies.length} source dependencies · Type:{" "}
                  {block.block_type}
                </small>
              </li>
            ))}
          </ul>
          {lineage.proposals.length > 0 && (
            <ul>
              {lineage.proposals.map((proposal) => (
                <li key={proposal.id}>
                  {humanBlockLabel(proposal.block_key)} ·{" "}
                  {proposal.validation_state}
                  {proposal.rejection_reason
                    ? ` · ${proposal.rejection_reason}`
                    : ""}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}
      <p className="inspector-disclaimer">
        A linked quotation shows where the wording appears. It does not confirm
        that a claim is complete or correct.
      </p>
    </div>
  );
}

function evidenceStateLabel(state: EvidenceState): string {
  const labels: Record<EvidenceState, string> = {
    quote_located: "Quote located",
    supported: "Supported",
    partial: "Partial",
    contradicted: "Contradicted",
    missing: "Missing",
    ambiguous: "Ambiguous",
    conflict: "Conflict",
    non_factual: "Non-factual",
  };
  return labels[state];
}

function assessmentMethodLabel(
  method: "mechanical" | "semantic_verifier" | "human",
) {
  return method === "semantic_verifier"
    ? "Semantic review"
    : method === "mechanical"
      ? "Exact quote match"
      : "Human review";
}

function humanBlockLabel(blockKey: string) {
  const paragraph = blockKey.match(/^paragraph:(\d+)$/);
  if (paragraph) return `Paragraph ${paragraph[1]}`;
  const slide = blockKey.match(/^slide:(\d+):/);
  if (slide) return `Slide ${slide[1]}`;
  return `Block ${blockKey}`;
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
              <small>
                Claims:{" "}
                {finding.material_claim_a_id === null
                  ? "unmapped"
                  : `#${finding.material_claim_a_id}`}{" "}
                /{" "}
                {finding.material_claim_b_id === null
                  ? "unmapped"
                  : `#${finding.material_claim_b_id}`}
              </small>
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
  lineage,
  warnings,
  warningsChecked,
  partialWarnings,
  checkingWarnings,
  busy,
  onLoadEvidence,
  onAnalyzeEvidence,
  onVerifyEvidence,
  onReviewEvidence,
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
  lineage: ArtifactLineage | undefined;
  warnings: WarningItem[];
  warningsChecked: boolean;
  partialWarnings: boolean;
  checkingWarnings: boolean;
  busy: boolean;
  onLoadEvidence: () => void;
  onAnalyzeEvidence: () => void;
  onVerifyEvidence: () => void;
  onReviewEvidence: (assessmentId: number, state: EvidenceState) => void;
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
            lineage={lineage}
            busy={busy}
            onLoad={onLoadEvidence}
            onAnalyze={onAnalyzeEvidence}
            onVerify={onVerifyEvidence}
            onReviewEvidence={onReviewEvidence}
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
