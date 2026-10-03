import { useEffect, useState } from "react";
import {
  ArrowRight,
  FileDiff,
  FileText,
  LoaderCircle,
  Pencil,
  RefreshCw,
  X,
} from "lucide-react";
import { api } from "../api";
import type {
  AffectedArtifact,
  SourceAssetInspection,
  SourcePackInspection,
  SourceRevisionStatus,
  SourceVersion,
} from "../types";
import { isRecord, outputLabel, sourceCharacterCount } from "../utils";

export function SourceRevisionPanel({
  transformationId,
  sourceVersion,
  revision,
  busy,
  onUpdated,
  onViewSource,
  onAffectedAction,
}: {
  transformationId: number;
  sourceVersion: SourceVersion;
  revision: SourceRevisionStatus | null;
  busy: boolean;
  onUpdated: (sourceText: string) => void;
  onViewSource: () => void;
  onAffectedAction: (
    action: "targeted" | "full",
    artifactRunId: number,
  ) => void;
}) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const [sourceText, setSourceText] = useState("");
  const [loadingSource, setLoadingSource] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourcePack, setSourcePack] = useState<SourcePackInspection | null>(
    null,
  );

  useEffect(() => {
    if (!editorOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setEditorOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [editorOpen]);

  useEffect(() => {
    let active = true;
    void api
      .sourcePack(transformationId)
      .then((pack) => {
        if (active) {
          setSourcePack(pack && Array.isArray(pack.versions) ? pack : null);
        }
      })
      .catch(() => {
        if (active) setSourcePack(null);
      });
    return () => {
      active = false;
    };
  }, [transformationId, sourceVersion.id]);

  async function openEditor() {
    setError(null);
    setLoadingSource(true);
    try {
      const body = await api.sourceVersion(sourceVersion.id);
      if (!isRecord(body) || typeof body.source_text !== "string") {
        throw new Error("Source could not be loaded.");
      }
      setSourceText(body.source_text);
      setEditorOpen(true);
    } catch {
      setError("The current source could not be opened. Please retry.");
    } finally {
      setLoadingSource(false);
    }
  }

  async function saveSource() {
    if (!sourceText.trim()) {
      setError("Source text cannot be empty.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.saveSourceVersion(transformationId, sourceText);
      setEditorOpen(false);
      setChangesOpen(false);
      onUpdated(sourceText);
    } catch {
      setError("The new source version could not be saved. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  const changeCount = revision?.changes.length ?? 0;
  const affected = revision?.potentially_affected_artifacts ?? [];
  const hasPrevious = Boolean(revision?.parent_source_version);
  const sourceMedia =
    sourcePack?.versions
      .find((item) => item.source_version_id === sourceVersion.id)
      ?.assets.filter((asset) =>
        ["image", "audio", "video"].includes(asset.source_kind),
      ) ?? [];

  return (
    <section className="source-revision" aria-label="Source version">
      <div className="source-revision__summary">
        <span className="source-revision__icon">
          <FileText aria-hidden="true" />
        </span>
        <div className="source-revision__copy">
          <strong>Source V{sourceVersion.version_number}</strong>
          <span>
            {hasPrevious
              ? changeCount +
                " change" +
                (changeCount === 1 ? "" : "s") +
                " from V" +
                revision?.parent_source_version?.version_number
              : "Current source"}
          </span>
        </div>
        {hasPrevious && affected.length > 0 && (
          <span className="source-revision__impact">
            {affected.length} may need review
          </span>
        )}
        {hasPrevious && (
          <button
            type="button"
            className="text-button source-revision__changes"
            onClick={() => setChangesOpen(!changesOpen)}
            aria-expanded={changesOpen}
          >
            <FileDiff aria-hidden="true" />
            {changesOpen ? "Hide changes" : "View changes"}
          </button>
        )}
        <button
          type="button"
          className="text-button source-revision__view"
          onClick={onViewSource}
        >
          <FileText aria-hidden="true" /> View source
        </button>
        <button
          type="button"
          className="button-secondary source-revision__update"
          onClick={() => void openEditor()}
          disabled={busy || loadingSource || saving}
        >
          {loadingSource ? (
            <LoaderCircle className="status-spin" aria-hidden="true" />
          ) : (
            <Pencil aria-hidden="true" />
          )}
          Update source
        </button>
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
      {sourceMedia.length > 0 && (
        <section className="source-media-panel" aria-label="Source media">
          <p className="eyebrow">Private source media</p>
          {sourceMedia.map((asset) => (
            <SourceMediaReview key={asset.id} asset={asset} />
          ))}
        </section>
      )}
      {changesOpen && revision && (
        <div className="source-revision__details">
          <div className="source-change-list">
            <h3>
              Changes from V{revision.parent_source_version?.version_number}
            </h3>
            {revision.changes.length ? (
              <ul>
                {revision.changes.map((change) => (
                  <li key={change.locator + change.change_type}>
                    <div className="source-change-list__heading">
                      <span
                        className={
                          "change-kind change-kind--" + change.change_type
                        }
                      >
                        {change.change_type}
                      </span>
                      <small>{change.locator}</small>
                    </div>
                    <div className="source-change-list__text">
                      {change.old_text && <del>{change.old_text}</del>}
                      {change.new_text && <ins>{change.new_text}</ins>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No text changes were detected between these versions.</p>
            )}
          </div>
          <div className="source-impact-list">
            <div>
              <p className="eyebrow">Review impact</p>
              <h3>Artifacts linked to changed source</h3>
              <p>
                An affected artifact references material that changed. Review
                the suggested update before accepting new content.
              </p>
            </div>
            {affected.length ? (
              <ul>
                {affected.map((item: AffectedArtifact) => (
                  <li key={item.artifact_version_id}>
                    <div className="source-impact-list__artifact">
                      <strong>{outputLabel(item.output_type)}</strong>
                      <span>Artifact V{item.artifact_version_number}</span>
                    </div>
                    {item.evidence_claims.length > 0 && (
                      <p>{item.evidence_claims[0]}</p>
                    )}
                    <p className="source-impact-list__state">
                      Impact:{" "}
                      {item.impact_state?.replaceAll("_", " ") ?? "unknown"}
                      {item.affected_block_keys?.length
                        ? " · affected blocks: " +
                          item.affected_block_keys.join(", ")
                        : ""}
                      {item.review_block_keys?.length
                        ? " · review blocks: " +
                          item.review_block_keys.join(", ")
                        : ""}
                    </p>
                    <div className="source-impact-list__actions">
                      <button
                        type="button"
                        className="button-primary button-primary--small"
                        onClick={() =>
                          onAffectedAction("targeted", item.artifact_run_id)
                        }
                        disabled={busy || !item.targeted_update_available}
                      >
                        <ArrowRight aria-hidden="true" />
                        {item.targeted_update_available
                          ? "Target affected blocks"
                          : "Targeted update needs review"}
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() =>
                          onAffectedAction("full", item.artifact_run_id)
                        }
                        disabled={busy}
                      >
                        <RefreshCw aria-hidden="true" />
                        Full regeneration
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="inspector-note">
                No linked evidence points to the changed source segments.
              </p>
            )}
          </div>
        </div>
      )}

      {editorOpen && (
        <div
          className="dialog-scrim"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !saving)
              setEditorOpen(false);
          }}
        >
          <section
            className="source-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-dialog-title"
          >
            <header className="source-dialog__header">
              <div>
                <p className="eyebrow">New immutable version</p>
                <h2 id="source-dialog-title">Update source</h2>
                <p>Source V{sourceVersion.version_number} stays unchanged.</p>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close source editor"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
              >
                <X aria-hidden="true" />
              </button>
            </header>
            <label htmlFor="source-revision-text">Source text</label>
            <textarea
              id="source-revision-text"
              rows={16}
              maxLength={20_000}
              value={sourceText}
              onChange={(event) => setSourceText(event.target.value)}
              autoFocus
            />
            <div className="source-dialog__footer">
              <span>
                {sourceCharacterCount(sourceText).toLocaleString()} / 20,000
              </span>
              <div>
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => setEditorOpen(false)}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="button-primary"
                  onClick={() => void saveSource()}
                  disabled={saving || !sourceText.trim()}
                >
                  {saving ? "Saving source…" : "Save new version"}
                </button>
              </div>
            </div>
            {error && (
              <p className="notice notice--error" role="alert">
                {error}
              </p>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

function SourceMediaReview({ asset }: { asset: SourceAssetInspection }) {
  const [rightsBasis, setRightsBasis] = useState(asset.rights_basis ?? "");
  const [consentState, setConsentState] = useState(asset.consent_state ?? "");
  const [consentRequired, setConsentRequired] = useState(
    asset.consent_required ?? false,
  );
  const [attribution, setAttribution] = useState(asset.attribution ?? "");
  const [eligible, setEligible] = useState(
    Boolean(
      asset.rights_basis &&
      asset.rights_basis !== "unknown" &&
      ["confirmed", "not_applicable"].includes(asset.consent_state ?? "") &&
      (!asset.consent_required || asset.consent_state === "confirmed"),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function saveRights() {
    if (!rightsBasis || !consentState) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.updateSourceMediaRights(asset.id, {
        rights_basis: rightsBasis as
          | "user_owned"
          | "permission_confirmed"
          | "public_domain"
          | "not_applicable"
          | "unknown",
        consent_state: consentState as
          "confirmed" | "not_applicable" | "unknown",
        consent_required: consentRequired,
        attribution: attribution || undefined,
      });
      setEligible(response.eligible_for_composition);
    } catch {
      setError("Source media rights could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="source-media-card">
      <header>
        <strong>
          {asset.original_filename || `${asset.source_kind} source`}
        </strong>
        <span>
          {asset.extraction_coverage.replaceAll("_", " ")} extraction ·{" "}
          {asset.extraction_method}
        </span>
      </header>
      {asset.preview_url && asset.source_kind === "image" && (
        <img
          className="source-media-card__preview"
          src={asset.preview_url}
          alt="Private source image"
        />
      )}
      {asset.preview_url && asset.source_kind === "audio" && (
        <audio controls preload="metadata" src={asset.preview_url} />
      )}
      {asset.preview_url && asset.source_kind === "video" && (
        <video controls preload="metadata" src={asset.preview_url} />
      )}
      {asset.download_url && (
        <a href={asset.download_url} download>
          Download original media
        </a>
      )}
      {asset.extraction_coverage === "unavailable" ? (
        <p>
          Media bytes are preserved privately. No extracted text is being
          treated as evidence.
        </p>
      ) : (
        <ul className="source-media-regions">
          {asset.regions.map((region) => (
            <li key={region.id}>
              <code>{region.locator}</code>
              {region.text ? (
                <span>{region.text}</span>
              ) : (
                <span>Locator only; no extracted text.</span>
              )}
              {region.locator_metadata?.timestamp_ms !== undefined && (
                <small>
                  At {String(region.locator_metadata.timestamp_ms)} ms
                </small>
              )}
            </li>
          ))}
        </ul>
      )}
      <details className="source-media-rights">
        <summary>Rights and consent</summary>
        <label>
          Rights basis
          <select
            value={rightsBasis}
            onChange={(event) => {
              setRightsBasis(event.target.value);
              setEligible(false);
            }}
            disabled={busy}
          >
            <option value="">Choose a rights basis</option>
            <option value="user_owned">I own this media</option>
            <option value="permission_confirmed">Permission confirmed</option>
            <option value="public_domain">Public domain</option>
            <option value="not_applicable">Not applicable</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label>
          Consent
          <select
            value={consentState}
            onChange={(event) => {
              setConsentState(event.target.value);
              setEligible(false);
            }}
            disabled={busy}
          >
            <option value="">Choose consent state</option>
            <option value="confirmed">Consent confirmed</option>
            <option value="not_applicable">Not applicable</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label className="source-media-rights__check">
          <input
            type="checkbox"
            checked={consentRequired}
            onChange={(event) => {
              setConsentRequired(event.target.checked);
              setEligible(false);
            }}
            disabled={busy}
          />
          Consent is required for this media
        </label>
        <label>
          Attribution (optional)
          <input
            value={attribution}
            maxLength={500}
            onChange={(event) => {
              setAttribution(event.target.value);
              setEligible(false);
            }}
            disabled={busy}
          />
        </label>
        <button
          type="button"
          className="button-secondary"
          onClick={() => void saveRights()}
          disabled={busy || !rightsBasis || !consentState}
        >
          {eligible ? "Rights confirmed" : "Save rights and consent"}
        </button>
        {error && (
          <p className="notice notice--error" role="alert">
            {error}
          </p>
        )}
        {!eligible && <small>Unknown rights remain visible for review.</small>}
      </details>
    </article>
  );
}
