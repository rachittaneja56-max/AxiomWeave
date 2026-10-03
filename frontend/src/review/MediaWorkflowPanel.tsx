import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import type {
  MediaAsset,
  MediaRender,
  MediaRights,
  OutputType,
  ReviewArtifactVersion,
  VideoPackageDocument,
} from "../types";
import { parseVideoPackage } from "../utils";

type RightsBasis =
  | "user_owned"
  | "permission_confirmed"
  | "public_domain"
  | "not_applicable"
  | "unknown"
  | "";
type ConsentState = "confirmed" | "not_applicable" | "unknown" | "";

type UploadedInput = {
  asset: MediaAsset;
  rightsBasis: RightsBasis;
  consentState: ConsentState;
  consentRequired: boolean;
  attribution: string;
  eligible: boolean;
};

type SceneInputs = { visual?: UploadedInput; audio?: UploadedInput };

const ACTIVE_RENDER_STATUSES = new Set(["pending", "rendering"]);

function mediaError(error: unknown): string {
  if (
    error instanceof ApiError &&
    error.body &&
    typeof error.body === "object"
  ) {
    const body = error.body as {
      detail?: { message?: unknown; code?: unknown };
      error?: { message?: unknown; code?: unknown };
    };
    const detail = body.error ?? body.detail;
    if (typeof detail?.message === "string") return detail.message;
    if (typeof detail?.code === "string")
      return detail.code.replaceAll("_", " ");
  }
  return "The media request could not be completed. Please retry.";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function setSceneInput(
  current: Record<number, SceneInputs>,
  index: number,
  key: "visual" | "audio",
  value: UploadedInput,
): Record<number, SceneInputs> {
  return { ...current, [index]: { ...current[index], [key]: value } };
}

function MediaAssetLink({
  asset,
  label,
}: {
  asset: MediaAsset;
  label: string;
}) {
  return (
    <a className="media-asset-link" href={asset.download_url} download>
      {label} · {formatBytes(asset.byte_size)}
    </a>
  );
}

function RightsControls({
  value,
  busy,
  onChange,
  onConfirm,
}: {
  value: UploadedInput;
  busy: boolean;
  onChange: (value: UploadedInput) => void;
  onConfirm: () => void;
}) {
  return (
    <fieldset className="media-rights-controls">
      <legend>Rights and consent</legend>
      <label>
        Rights basis
        <select
          value={value.rightsBasis}
          onChange={(event) =>
            onChange({
              ...value,
              rightsBasis: event.target.value as RightsBasis,
              eligible: false,
            })
          }
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
          value={value.consentState}
          onChange={(event) =>
            onChange({
              ...value,
              consentState: event.target.value as ConsentState,
              eligible: false,
            })
          }
          disabled={busy}
        >
          <option value="">Choose consent state</option>
          <option value="confirmed">Consent confirmed</option>
          <option value="not_applicable">Not applicable</option>
          <option value="unknown">Unknown</option>
        </select>
      </label>
      <label className="media-rights-controls__check">
        <input
          type="checkbox"
          checked={value.consentRequired}
          onChange={(event) =>
            onChange({
              ...value,
              consentRequired: event.target.checked,
              eligible: false,
            })
          }
          disabled={busy}
        />
        Consent is required for this asset
      </label>
      <label>
        Attribution (optional)
        <input
          value={value.attribution}
          maxLength={500}
          onChange={(event) =>
            onChange({
              ...value,
              attribution: event.target.value,
              eligible: false,
            })
          }
          disabled={busy}
        />
      </label>
      <button
        type="button"
        className="button-secondary"
        disabled={
          busy || !value.rightsBasis || !value.consentState || value.eligible
        }
        onClick={onConfirm}
      >
        {value.eligible ? "Rights confirmed" : "Confirm rights and consent"}
      </button>
      {!value.eligible && (
        <small>
          Unresolved rights keep this upload out of video composition.
        </small>
      )}
    </fieldset>
  );
}

export function MediaWorkflowPanel({
  outputType,
  version,
}: {
  outputType: OutputType;
  version: ReviewArtifactVersion | null;
}) {
  const enabled =
    outputType === "infographic" || outputType === "video_package";
  const video = useMemo<VideoPackageDocument | null>(
    () =>
      outputType === "video_package"
        ? parseVideoPackage(version?.content ?? "")
        : null,
    [outputType, version?.content],
  );
  const artifactVersionId = version?.id;
  const [renders, setRenders] = useState<MediaRender[]>([]);
  const [render, setRender] = useState<MediaRender | null>(null);
  const [sceneInputs, setSceneInputs] = useState<Record<number, SceneInputs>>(
    {},
  );
  const [durationSeconds, setDurationSeconds] = useState<
    Record<number, string>
  >({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRender(null);
    setRenders([]);
    setSceneInputs({});
    setDurationSeconds({});
    setError(null);
    if (!enabled || artifactVersionId == null) return;
    void api
      .listMediaRenders(artifactVersionId)
      .then((items) => {
        if (cancelled || !Array.isArray(items)) return;
        setRenders(items);
        setRender(items[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setRenders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, artifactVersionId]);

  useEffect(() => {
    if (!render || !ACTIVE_RENDER_STATUSES.has(render.status)) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void api
        .getMediaRender(render.id)
        .then((fresh) => {
          if (cancelled) return;
          setRender(fresh);
          setRenders((current) =>
            [fresh, ...current.filter((item) => item.id !== fresh.id)].sort(
              (left, right) => right.id - left.id,
            ),
          );
        })
        .catch((requestError: unknown) => {
          if (!cancelled) setError(mediaError(requestError));
        });
    }, 1_500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [render]);

  if (!enabled || !version) return null;

  async function uploadInput(
    sceneIndex: number,
    key: "visual" | "audio",
    file: File | undefined,
  ) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const asset = await api.uploadSceneAsset(
        file,
        key === "visual" ? "scene_visual_upload" : "scene_audio_upload",
      );
      const initial: UploadedInput = {
        asset,
        rightsBasis: "",
        consentState: "",
        consentRequired: false,
        attribution: "",
        eligible: false,
      };
      setSceneInputs((current) =>
        setSceneInput(current, sceneIndex, key, initial),
      );
    } catch (requestError) {
      setError(mediaError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRights(sceneIndex: number, key: "visual" | "audio") {
    const value = sceneInputs[sceneIndex]?.[key];
    if (!value || !value.rightsBasis || !value.consentState) return;
    setBusy(true);
    setError(null);
    try {
      const rights: MediaRights = await api.updateMediaRights(value.asset.id, {
        rights_basis: value.rightsBasis as Exclude<RightsBasis, "">,
        consent_state: value.consentState as Exclude<ConsentState, "">,
        consent_required: value.consentRequired,
        attribution: value.attribution || undefined,
      });
      setSceneInputs((current) =>
        setSceneInput(current, sceneIndex, key, {
          ...value,
          eligible: rights.eligible_for_composition,
        }),
      );
    } catch (requestError) {
      setError(mediaError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function startRender() {
    if (!version) return;
    setBusy(true);
    setError(null);
    try {
      const body: {
        scene_durations_ms?: (number | null)[];
        scene_media?: {
          scene_index: number;
          visual_asset_id?: number;
          audio_asset_id?: number;
        }[];
      } = {};
      if (video) {
        body.scene_durations_ms = video.scenes.map((_, index) => {
          const seconds = durationSeconds[index]?.trim();
          return seconds ? Math.round(Number(seconds) * 1_000) : null;
        });
        body.scene_media = video.scenes.flatMap((_, index) => {
          const inputs = sceneInputs[index];
          const visual = inputs?.visual?.eligible
            ? inputs.visual.asset.id
            : undefined;
          const audio = inputs?.audio?.eligible
            ? inputs.audio.asset.id
            : undefined;
          return visual || audio
            ? [
                {
                  scene_index: index,
                  visual_asset_id: visual,
                  audio_asset_id: audio,
                },
              ]
            : [];
        });
      }
      const next = await api.startMediaRender(version.id, body);
      setRender(next);
      setRenders((current) => [
        next,
        ...current.filter((item) => item.id !== next.id),
      ]);
    } catch (requestError) {
      setError(mediaError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function retryFailedTask() {
    if (!render) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.retryMediaTask(render.id);
      setRender(next);
    } catch (requestError) {
      setError(mediaError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function review(decision: "approved" | "rejected") {
    if (!render) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.reviewMediaRender(render.id, decision);
      setRender(next);
      setRenders((current) =>
        current.map((item) => (item.id === next.id ? next : item)),
      );
    } catch (requestError) {
      setError(mediaError(requestError));
    } finally {
      setBusy(false);
    }
  }

  const allAssets = render?.tasks.flatMap((task) => task.assets) ?? [];
  const captions = allAssets.find((asset) => asset.purpose === "caption_vtt");
  const failedTask =
    render?.tasks.some((task) => task.status === "failed") ?? false;

  return (
    <section
      className="media-workflow-panel"
      aria-labelledby="media-workflow-title"
    >
      <header className="media-workflow-panel__header">
        <div>
          <p className="eyebrow">Private media workflow</p>
          <h3 id="media-workflow-title">
            {outputType === "infographic"
              ? "Rendered infographic"
              : "Rendered video"}
          </h3>
          <p>
            Outputs remain tied to Artifact Version {version.version_number}.
          </p>
        </div>
        <button
          type="button"
          className="button-primary"
          onClick={() => void startRender()}
          disabled={busy}
        >
          {busy
            ? "Working…"
            : outputType === "infographic"
              ? "Render infographic"
              : "Render video"}
        </button>
      </header>

      {video && (
        <div className="media-scene-controls">
          <p>
            Scene timing starts from an operational text pacing estimate. It is
            not a narration quality score.
          </p>
          {video.scenes.map((scene, index) => {
            const inputs = sceneInputs[index] ?? {};
            return (
              <fieldset
                className="media-scene-control"
                key={`${version.id}-${index}`}
              >
                <legend>
                  Scene {index + 1}: {scene.title}
                </legend>
                <label>
                  Duration in seconds (blank uses the initial estimate)
                  <input
                    type="number"
                    min="1"
                    max="180"
                    step="0.5"
                    value={durationSeconds[index] ?? ""}
                    onChange={(event) =>
                      setDurationSeconds((current) => ({
                        ...current,
                        [index]: event.target.value,
                      }))
                    }
                    disabled={busy}
                  />
                </label>
                <div className="media-scene-control__uploads">
                  {(["visual", "audio"] as const).map((key) => {
                    const input = inputs[key];
                    const id = `scene-${index}-${key}-upload`;
                    return (
                      <div className="media-input-card" key={key}>
                        <label htmlFor={id}>
                          {key === "visual"
                            ? "Optional scene image (PNG/JPEG)"
                            : "Optional narration audio (WAV/MP3/M4A)"}
                        </label>
                        <input
                          id={id}
                          type="file"
                          accept={
                            key === "visual"
                              ? ".png,.jpg,.jpeg,image/png,image/jpeg"
                              : ".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
                          }
                          onChange={(event) =>
                            void uploadInput(
                              index,
                              key,
                              event.target.files?.[0],
                            )
                          }
                          disabled={busy}
                        />
                        {input && (
                          <>
                            {key === "visual" ? (
                              <img
                                className="media-input-card__preview"
                                src={input.asset.preview_url}
                                alt={`User supplied visual for scene ${index + 1}`}
                              />
                            ) : (
                              <audio controls src={input.asset.preview_url} />
                            )}
                            <RightsControls
                              value={input}
                              busy={busy}
                              onChange={(next) =>
                                setSceneInputs((current) =>
                                  setSceneInput(current, index, key, next),
                                )
                              }
                              onConfirm={() => void confirmRights(index, key)}
                            />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </fieldset>
            );
          })}
        </div>
      )}

      {renders.length > 1 && (
        <label className="media-render-history">
          Render history for this exact artifact version
          <select
            value={render?.id ?? ""}
            onChange={(event) => {
              const selected = renders.find(
                (item) => item.id === Number(event.target.value),
              );
              if (selected) setRender(selected);
            }}
          >
            {renders.map((item) => (
              <option key={item.id} value={item.id}>
                Render {item.id} · {item.status}
              </option>
            ))}
          </select>
        </label>
      )}

      {error && (
        <p className="media-workflow-panel__error" role="alert">
          {error}
        </p>
      )}
      {render && (
        <div className="media-render-result" aria-live="polite">
          <p className="media-render-result__status" role="status">
            Render {render.id}: {render.status.replaceAll("_", " ")}
            {render.failure_code ? ` · ${render.failure_code}` : ""}
          </p>
          {render.status === "pending" || render.status === "rendering" ? (
            <p>
              Media tasks are processing. Successful scene images remain
              available if another scene fails.
            </p>
          ) : null}
          {render.tasks.length > 0 && (
            <ul className="media-task-list">
              {render.tasks.map((task) => (
                <li key={task.id}>
                  <span>
                    {task.task_key.replace(":", " ")}:{" "}
                    {task.status.replaceAll("_", " ")}
                  </span>
                  {task.failure_code && <small>{task.failure_code}</small>}
                  {task.assets
                    .filter((asset) => asset.purpose === "video_scene_frame")
                    .map((asset) => (
                      <img
                        key={asset.id}
                        className="media-scene-preview"
                        src={asset.preview_url}
                        alt={`Rendered ${task.task_key}`}
                      />
                    ))}
                </li>
              ))}
            </ul>
          )}
          {render.primary_asset && (
            <div className="media-primary-preview">
              {render.artifact_family === "video_package" ? (
                <video
                  controls
                  preload="metadata"
                  src={render.primary_asset.preview_url}
                />
              ) : (
                <img
                  src={render.primary_asset.preview_url}
                  alt="Private infographic preview"
                />
              )}
              <MediaAssetLink
                asset={render.primary_asset}
                label={
                  render.artifact_family === "video_package"
                    ? "Download MP4"
                    : "Download PNG"
                }
              />
            </div>
          )}
          {outputType === "infographic" &&
            allAssets
              .filter((asset) => asset.purpose === "infographic_svg")
              .map((asset) => (
                <MediaAssetLink
                  key={asset.id}
                  asset={asset}
                  label="Download SVG"
                />
              ))}
          {captions && (
            <MediaAssetLink asset={captions} label="Download captions (VTT)" />
          )}
          {failedTask && (
            <button
              type="button"
              className="button-secondary"
              onClick={() => void retryFailedTask()}
              disabled={busy}
            >
              Retry failed media task
            </button>
          )}
          {render.status === "ready_for_review" && (
            <div className="media-review-actions">
              <button
                type="button"
                className="button-primary"
                onClick={() => void review("approved")}
                disabled={busy}
              >
                Approve media quality
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={() => void review("rejected")}
                disabled={busy}
              >
                Reject render
              </button>
            </div>
          )}
          {(render.status === "approved" || render.status === "rejected") && (
            <p>
              Media decision: {render.status}. A re-render creates a separate
              review target.
            </p>
          )}
          <p className="media-review-disclaimer">{render.review_copy}</p>
          {render.reviews.length > 0 && (
            <details>
              <summary>Human media review history</summary>
              <ol>
                {render.reviews.map((item, index) => (
                  <li key={`${item.created_at}-${index}`}>
                    {item.decision} by reviewer {item.reviewer_user_id} at{" "}
                    {new Date(item.created_at).toLocaleString()} · asset SHA-256{" "}
                    {item.primary_asset_hash.slice(0, 12)}
                    {item.note ? ` · ${item.note}` : ""}
                  </li>
                ))}
              </ol>
            </details>
          )}
          {render.metrics.length > 0 && (
            <details>
              <summary>Render measurements</summary>
              <ul>
                {render.metrics.map((metric, index) => (
                  <li key={`${metric.operation_type}-${index}`}>
                    {metric.operation_type}: {metric.elapsed_ms} ms,{" "}
                    {formatBytes(metric.output_bytes)} output ·{" "}
                    {metric.tool_version}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
