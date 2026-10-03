import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, RefreshCw, GitBranch, X } from "lucide-react";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { ArtifactRail } from "../review/ArtifactRail";
import { ArtifactViewer } from "../review/ArtifactViewer";
import { InspectorPanel } from "../review/InspectorPanel";
import { SourceRevisionPanel } from "../review/SourceRevisionPanel";
import { SourceViewerDialog } from "../review/SourceViewerDialog";
import type {
  DiscrepancyFinding,
  EvidenceLink,
  InspectorTab,
  OutputType,
  ReviewArtifactRun,
  ReviewArtifactVersion,
  SourceRevisionStatus,
  SourceVersionContent,
  TransformationDetail,
} from "../types";
import {
  deriveTransformationTitle,
  artifactExportText,
  isRecord,
  isSourceRevisionStatus,
  isTransformationDetail,
  outputLabel,
  parsePresentation,
} from "../utils";

function pairKey(left: number, right: number): string {
  return [left, right].sort((a, b) => a - b).join(":");
}

export function ReviewWorkspace({
  transformationId,
  initialOutputType,
  onBack,
  onTitleChange,
  onSourceVersionChange,
}: {
  transformationId: number;
  initialOutputType?: OutputType;
  onBack: () => void;
  onTitleChange: (title: string) => void;
  onSourceVersionChange: (version: number) => void;
}) {
  const [detail, setDetail] = useState<TransformationDetail | null>(null);
  const [revision, setRevision] = useState<SourceRevisionStatus | null>(null);
  const [activeArtifactId, setActiveArtifactId] = useState<number | null>(null);
  const [selectedVersions, setSelectedVersions] = useState<
    Record<number, number>
  >({});
  const [activeTab, setActiveTab] = useState<InspectorTab>("evidence");
  const [evidenceByVersion, setEvidenceByVersion] = useState<
    Record<number, EvidenceLink[]>
  >({});
  const [findingsByPair, setFindingsByPair] = useState<
    Record<string, DiscrepancyFinding | null>
  >({});
  const [warningsChecked, setWarningsChecked] = useState(false);
  const [failedPairIds, setFailedPairIds] = useState<[number, number][]>([]);
  const [partialWarnings, setPartialWarnings] = useState(false);
  const [loading, setLoading] = useState(true);
  const [checkingWarnings, setCheckingWarnings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [traceabilityOpen, setTraceabilityOpen] = useState(false);
  const [sourceViewer, setSourceViewer] = useState<{
    source: SourceVersionContent;
    quote?: string | null;
  } | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const traceabilityTrigger = useRef<HTMLButtonElement>(null);
  const traceabilityDialog = useRef<HTMLElement>(null);

  const closeTraceability = useCallback(() => setTraceabilityOpen(false), []);
  const closeSourceViewer = useCallback(() => setSourceViewer(null), []);

  async function openSourceViewer(
    sourceVersionId: number,
    quote?: string | null,
  ) {
    setTraceabilityOpen(false);
    setSourceLoading(true);
    try {
      const body = await api.sourceVersion(sourceVersionId);
      if (
        !isRecord(body) ||
        typeof body.source_text !== "string" ||
        typeof body.version_number !== "number"
      )
        throw new Error("invalid source");
      setSourceViewer({ source: body as SourceVersionContent, quote });
    } catch {
      setActionError("The source version could not be opened. Please retry.");
    } finally {
      setSourceLoading(false);
    }
  }

  useEffect(() => {
    if (!traceabilityOpen) traceabilityTrigger.current?.focus();
  }, [traceabilityOpen]);

  useEffect(() => {
    if (!traceabilityOpen) return;
    traceabilityDialog.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setTraceabilityOpen(false);
      if (event.key === "Tab") {
        const items = traceabilityDialog.current?.querySelectorAll<HTMLElement>(
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
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [traceabilityOpen]);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const detailBody = await api.transformation(transformationId);
        if (!isTransformationDetail(detailBody)) {
          throw new Error("Unexpected review response.");
        }
        let revisionBody: unknown = null;
        try {
          revisionBody = await api.revisionImpact(transformationId);
        } catch {
          revisionBody = null;
        }
        if (!active) return;
        setDetail(detailBody);
        onSourceVersionChange(detailBody.source_version.version_number);
        setRevision(isSourceRevisionStatus(revisionBody) ? revisionBody : null);
        setActiveArtifactId((current) => {
          if (
            current !== null &&
            detailBody.artifact_runs.some(
              (artifact) => artifact.artifact_run_id === current,
            )
          ) {
            return current;
          }
          return (
            detailBody.artifact_runs.find(
              (artifact) => artifact.output_type === initialOutputType,
            )?.artifact_run_id ??
            detailBody.artifact_runs[0]?.artifact_run_id ??
            null
          );
        });
        setSelectedVersions((current) => {
          const retained: Record<number, number> = {};
          for (const artifact of detailBody.artifact_runs) {
            const selected = current[artifact.artifact_run_id];
            if (artifact.versions.some((version) => version.id === selected)) {
              retained[artifact.artifact_run_id] = selected;
            }
          }
          return retained;
        });
      } catch {
        if (active)
          setError("Could not open this review workspace. Please retry.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [transformationId, reload, initialOutputType, onSourceVersionChange]);

  const hasActiveGeneration = Boolean(
    detail?.artifact_runs.some(
      (artifact) =>
        artifact.status === "pending" || artifact.status === "running",
    ),
  );

  useEffect(() => {
    if (!hasActiveGeneration) return;
    let active = true;
    let pollCount = 0;
    let timeoutId: number | undefined;

    async function poll() {
      if (!active || pollCount >= 150) return;
      pollCount += 1;
      try {
        const body = await api.transformation(transformationId);
        if (!active || !isTransformationDetail(body)) return;
        setDetail(body);
        const stillActive = body.artifact_runs.some(
          (artifact) =>
            artifact.status === "pending" || artifact.status === "running",
        );
        if (stillActive && pollCount < 150) {
          timeoutId = window.setTimeout(() => void poll(), 2000);
        }
      } catch {
        if (active && pollCount < 150) {
          timeoutId = window.setTimeout(() => void poll(), 5000);
        }
      }
    }

    timeoutId = window.setTimeout(() => void poll(), 1500);
    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [transformationId, hasActiveGeneration]);

  const artifacts = detail?.artifact_runs ?? [];
  const activeArtifact: ReviewArtifactRun | null =
    artifacts.find(
      (artifact) => artifact.artifact_run_id === activeArtifactId,
    ) ?? null;
  const latestVersion = activeArtifact?.versions.at(-1) ?? null;
  const selectedVersion: ReviewArtifactVersion | null =
    activeArtifact?.versions.find(
      (version) =>
        version.id === selectedVersions[activeArtifact.artifact_run_id],
    ) ??
    latestVersion ??
    null;
  const isLatest = Boolean(
    selectedVersion && selectedVersion.id === latestVersion?.id,
  );

  const warnings = useMemo(() => {
    if (!detail) return [];
    const versions = new Map<number, { label: string }>();
    for (const artifact of detail.artifact_runs) {
      const latest = artifact.versions.at(-1);
      if (latest)
        versions.set(latest.id, { label: outputLabel(artifact.output_type) });
    }
    return Object.values(findingsByPair)
      .filter((finding): finding is DiscrepancyFinding => finding !== null)
      .map((finding) => ({
        finding,
        labelA:
          versions.get(finding.artifact_version_a_id)?.label ?? "Artifact",
        labelB:
          versions.get(finding.artifact_version_b_id)?.label ?? "Artifact",
      }));
  }, [detail, findingsByPair]);

  function setActionError(messageText: string) {
    setError(messageText);
    setMessage(null);
  }

  async function refreshReview() {
    setReload((value) => value + 1);
  }

  async function runAction(action: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
      await refreshReview();
    } catch {
      setActionError(fallback);
    } finally {
      setBusy(false);
    }
  }

  async function saveVersion(content: string) {
    if (!activeArtifact) return;
    if (
      activeArtifact.output_type === "presentation" &&
      !parsePresentation(content)
    ) {
      setActionError(
        "This presentation could not be saved. Review its slide fields and try again.",
      );
      return;
    }
    await runAction(
      () => api.saveArtifactVersion(activeArtifact.artifact_run_id, content),
      "This version could not be saved. Please retry.",
    );
  }

  async function regenerateArtifact(artifactRunId: number) {
    await runAction(
      () => api.regenerateArtifact(artifactRunId),
      "This artifact could not be regenerated. Please retry.",
    );
  }

  async function targetUpdateArtifact(artifactRunId: number) {
    await runAction(
      () => api.targetedUpdate(artifactRunId),
      "The targeted update could not be completed. Please retry.",
    );
  }

  async function retryArtifact(artifactRunId: number) {
    await runAction(
      () => api.retryArtifact(artifactRunId),
      "This artifact could not be retried. Please try again.",
    );
  }

  async function updateReviewStatus(
    artifactVersionId: number,
    status: "accepted" | "rejected",
  ) {
    await runAction(
      () => api.reviewArtifact(artifactVersionId, status),
      "The review decision could not be saved. Please retry.",
    );
    if (status === "accepted" && !error) setMessage("Artifact accepted.");
  }

  async function loadEvidence(versionId: number) {
    setError(null);
    try {
      const body = await api.evidence(versionId);
      if (!Array.isArray(body))
        throw new Error("Unexpected evidence response.");
      setEvidenceByVersion((current) => ({
        ...current,
        [versionId]: body as EvidenceLink[],
      }));
    } catch {
      setActionError("Saved evidence could not be loaded. Please retry.");
    }
  }

  async function analyzeEvidence(version: ReviewArtifactVersion) {
    setBusy(true);
    setError(null);
    try {
      const body = await api.analyzeEvidence(
        version.id,
        version.source_version_id,
      );
      if (!Array.isArray(body))
        throw new Error("Unexpected evidence response.");
      setEvidenceByVersion((current) => ({
        ...current,
        [version.id]: body as EvidenceLink[],
      }));
      await refreshReview();
    } catch {
      setActionError("Claims could not be analyzed. Please retry.");
      setReload((value) => value + 1);
    } finally {
      setBusy(false);
    }
  }

  async function resumeClaimScan(scanId: number) {
    setBusy(true);
    setError(null);
    try {
      await api.resumeClaimScan(scanId);
      await refreshReview();
    } catch {
      setActionError("Incomplete claim batches could not be resumed.");
      setReload((value) => value + 1);
    } finally {
      setBusy(false);
    }
  }

  async function checkSiblingConsistency() {
    if (artifacts.length < 2) {
      setMessage("Add at least two artifacts to compare sibling consistency.");
      return;
    }
    setCheckingWarnings(true);
    setError(null);
    setMessage(null);
    const next: Record<string, DiscrepancyFinding | null> = {};
    const withVersions = artifacts
      .map((artifact) => ({
        artifact,
        version: artifact.versions.at(-1),
      }))
      .filter(
        (
          entry,
        ): entry is {
          artifact: ReviewArtifactRun;
          version: ReviewArtifactVersion;
        } => Boolean(entry.version),
      );
    const allPairs: [number, number][] = [];
    for (let left = 0; left < withVersions.length; left += 1) {
      for (let right = left + 1; right < withVersions.length; right += 1) {
        allPairs.push([
          withVersions[left].version.id,
          withVersions[right].version.id,
        ]);
      }
    }
    const pairs = failedPairIds.length ? failedPairIds : allPairs;
    const byVersionId = new Map(
      withVersions.map(({ version }) => [version.id, version]),
    );
    const failed: [number, number][] = [];
    let succeeded = 0;
    for (const [aId, bId] of pairs) {
      const a = byVersionId.get(aId);
      const b = byVersionId.get(bId);
      if (!a || !b) continue;
      const key = pairKey(a.id, b.id);
      try {
        const body = await api.analyzeDiscrepancy(a.id, b.id);
        if (!isRecord(body)) throw new Error("Unexpected warning response.");
        const finding =
          isRecord(body.finding) && Number.isInteger(body.finding.id)
            ? (body.finding as unknown as DiscrepancyFinding)
            : null;
        next[key] = finding;
        succeeded += 1;
      } catch {
        failed.push([aId, bId]);
      }
    }
    setCheckingWarnings(false);
    if (succeeded > 0) {
      setFindingsByPair((current) => ({ ...current, ...next }));
      setWarningsChecked(true);
    }
    setFailedPairIds(failed);
    setPartialWarnings(failed.length > 0 && succeeded > 0);
    if (failed.length > 0 && succeeded === 0) {
      setActionError("Sibling consistency could not be checked. Please retry.");
    }
  }

  async function dismissWarning(finding: DiscrepancyFinding) {
    setBusy(true);
    setError(null);
    try {
      const body = await api.dismissDiscrepancy(finding.id);
      if (!isRecord(body)) throw new Error("Unexpected warning response.");
      const updated = body as unknown as DiscrepancyFinding;
      setFindingsByPair((current) => ({
        ...current,
        [pairKey(updated.artifact_version_a_id, updated.artifact_version_b_id)]:
          updated,
      }));
    } catch {
      setActionError("The warning could not be dismissed. Please retry.");
    } finally {
      setBusy(false);
    }
  }

  async function copyArtifact(outputType: OutputType, content: string) {
    try {
      await navigator.clipboard.writeText(
        artifactExportText(outputType, content),
      );
      setExportStatus("Artifact copied to clipboard.");
    } catch {
      setExportStatus("Clipboard access is unavailable in this browser.");
    }
  }

  function downloadArtifact(outputType: OutputType, content: string) {
    const label = outputLabel(outputType);
    const filename =
      label
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/(^-|-$)/g, "") + ".md";
    const url = URL.createObjectURL(
      new Blob([artifactExportText(outputType, content)], {
        type: "text/markdown;charset=utf-8",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
    setExportStatus(label + " Markdown downloaded.");
  }

  async function downloadPowerPoint(content: string) {
    const presentation = parsePresentation(content);
    if (!presentation) {
      setExportStatus("This presentation could not be exported.");
      return;
    }
    try {
      const { renderPresentationPptx, presentationFilename } =
        await import("../pptx");
      const blob = await renderPresentationPptx(presentation);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = presentationFilename(presentation.title);
      anchor.click();
      URL.revokeObjectURL(url);
      setExportStatus("Editable PowerPoint downloaded.");
    } catch (error) {
      setExportStatus(
        error instanceof Error && error.message.startsWith("This slide")
          ? error.message
          : "PowerPoint export failed. Please try again.",
      );
    }
  }

  function handleSourceUpdated(sourceText: string) {
    onTitleChange(deriveTransformationTitle(sourceText));
    void refreshReview();
  }

  if (loading && !detail) {
    return (
      <div className="review-loading" role="status">
        <LoaderCircle className="status-spin" aria-hidden="true" />
        <span>Opening your review workspace…</span>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="review-load-error" role="alert">
        <p>{error ?? "This review workspace could not be opened."}</p>
        <button
          type="button"
          className="button-secondary"
          onClick={() => setReload((value) => value + 1)}
        >
          <RefreshCw aria-hidden="true" />
          Retry
        </button>
        <button type="button" className="text-button" onClick={onBack}>
          Back to transformations
        </button>
      </div>
    );
  }

  return (
    <section className="review-screen" aria-label="Artifact review workspace">
      <div className="review-context">
        <div className="review-context__source">
          <span className="source-kind__dot" />
          <strong>Source V{detail.source_version.version_number}</strong>
          <span>
            One source, {detail.artifact_runs.length} artifact
            {detail.artifact_runs.length === 1 ? "" : "s"}
          </span>
        </div>
        {activeArtifact?.context_manifest && (
          <span
            className={
              activeArtifact.context_manifest.state === "needs_review"
                ? "review-context__plan review-context__plan--warning"
                : "review-context__plan"
            }
            role="status"
          >
            Latest context plan: {activeArtifact.context_manifest.route}
            {" · Pack V"}
            {activeArtifact.context_manifest.source_pack_version_id}
            {" · "}
            {activeArtifact.context_manifest.region_count} regions
            {activeArtifact.context_manifest.state === "needs_review" &&
              " · Needs review"}
            {activeArtifact.context_manifest.extraction_coverage ===
              "partial" && " · Partial extraction"}
          </span>
        )}
        <StatusBadge
          status={
            detail.status === "Partial Failure"
              ? "Needs attention"
              : detail.status === "Review Required"
                ? "Ready for review"
                : detail.status
          }
          compact
        />
      </div>
      <SourceRevisionPanel
        transformationId={detail.transformation_run_id}
        sourceVersion={detail.source_version}
        revision={revision}
        busy={busy}
        onUpdated={handleSourceUpdated}
        onViewSource={() => void openSourceViewer(detail.source_version.id)}
        onAffectedAction={(action, artifactRunId) => {
          if (action === "targeted") void targetUpdateArtifact(artifactRunId);
          else void regenerateArtifact(artifactRunId);
        }}
      />
      <ArtifactRail
        artifacts={artifacts}
        activeArtifactId={activeArtifact?.artifact_run_id ?? null}
        sourceVersion={detail.source_version.version_number}
        onSourceSelect={() => void openSourceViewer(detail.source_version.id)}
        onSelect={(artifactRunId) => {
          setActiveArtifactId(artifactRunId);
          setActiveTab("evidence");
          setExportStatus(null);
        }}
      />
      {(error || message) && (
        <p
          className={error ? "notice notice--error" : "notice"}
          role={error ? "alert" : "status"}
        >
          {error ?? message}
        </p>
      )}
      {artifacts.length === 0 ? (
        <div className="review-empty">
          <div className="review-empty__icon">A</div>
          <div>
            <p className="eyebrow">Review workspace</p>
            <h2>No artifacts yet</h2>
            <p>
              Return to your transformations to generate the selected materials.
            </p>
            <button type="button" className="button-secondary" onClick={onBack}>
              Back to transformations
            </button>
          </div>
        </div>
      ) : (
        <div className="review-layout">
          {activeArtifact ? (
            <ArtifactViewer
              artifact={activeArtifact}
              version={selectedVersion}
              isLatest={isLatest}
              busy={busy}
              exportStatus={exportStatus}
              onEdit={() => {
                setError(null);
                setExportStatus(null);
              }}
              onSave={(content) => void saveVersion(content)}
              onCancelEdit={() => setError(null)}
              onRegenerate={() =>
                void regenerateArtifact(activeArtifact.artifact_run_id)
              }
              onRetry={() => void retryArtifact(activeArtifact.artifact_run_id)}
              onReviewStatus={(status) =>
                selectedVersion &&
                void updateReviewStatus(selectedVersion.id, status)
              }
              onCopy={copyArtifact}
              onDownload={downloadArtifact}
              onPowerpointExport={(content) => void downloadPowerPoint(content)}
              onTraceability={(trigger) => {
                traceabilityTrigger.current = trigger;
                setTraceabilityOpen(true);
              }}
            />
          ) : (
            <div className="review-empty">
              <p>No artifact is available to review yet.</p>
            </div>
          )}
          <button
            type="button"
            className="button-secondary traceability-trigger"
            ref={traceabilityTrigger}
            onClick={() => setTraceabilityOpen(true)}
          >
            <GitBranch aria-hidden="true" /> Traceability
          </button>
          {traceabilityOpen && (
            <div
              className="traceability-scrim"
              onMouseDown={() => setTraceabilityOpen(false)}
            >
              <section
                className="traceability-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="traceability-title"
                tabIndex={-1}
                ref={traceabilityDialog}
                onMouseDown={(event) => event.stopPropagation()}
              >
                <div className="traceability-modal__heading">
                  <h2 id="traceability-title">Traceability</h2>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Close traceability"
                    onClick={closeTraceability}
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
                <InspectorPanel
                  activeTab={activeTab}
                  onTabChange={setActiveTab}
                  detail={detail}
                  sourceVersion={detail.source_version}
                  artifact={activeArtifact}
                  version={selectedVersion}
                  selectedVersionId={selectedVersion?.id ?? null}
                  evidence={
                    selectedVersion
                      ? evidenceByVersion[selectedVersion.id]
                      : undefined
                  }
                  warnings={warnings}
                  warningsChecked={warningsChecked}
                  partialWarnings={partialWarnings}
                  checkingWarnings={checkingWarnings}
                  busy={busy}
                  onLoadEvidence={() =>
                    selectedVersion && void loadEvidence(selectedVersion.id)
                  }
                  onAnalyzeEvidence={() =>
                    selectedVersion && void analyzeEvidence(selectedVersion)
                  }
                  onResumeClaimScan={(scanId) => void resumeClaimScan(scanId)}
                  onViewSource={(sourceVersionId, quote) =>
                    void openSourceViewer(sourceVersionId, quote)
                  }
                  onCheckWarnings={() => void checkSiblingConsistency()}
                  onDismissWarning={(finding) => void dismissWarning(finding)}
                  onSelectVersion={(versionId) => {
                    if (!activeArtifact) return;
                    setSelectedVersions((current) => ({
                      ...current,
                      [activeArtifact.artifact_run_id]: versionId,
                    }));
                  }}
                />
              </section>
            </div>
          )}
          {sourceLoading && (
            <div className="visually-hidden" role="status">
              Loading source…
            </div>
          )}
          {sourceViewer && (
            <SourceViewerDialog
              source={sourceViewer.source}
              quote={sourceViewer.quote}
              onClose={closeSourceViewer}
            />
          )}
        </div>
      )}
      <p className="review-footer-note">
        A review decision records your workflow choice. It does not certify
        factual accuracy.
      </p>
    </section>
  );
}
