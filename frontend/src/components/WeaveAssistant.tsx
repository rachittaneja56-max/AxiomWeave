import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Check,
  FileUp,
  Link2,
  LoaderCircle,
  MessageCircle,
  Minus,
  Paperclip,
  Send,
  X,
} from "lucide-react";
import { ApiError, api } from "../api";
import { OUTPUT_TYPES } from "../types";
import { deriveTransformationTitle, isExtractedText, isRecord } from "../utils";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  action_plan_id: number | null;
};

type PlanStep = {
  id: number;
  ordinal: number;
  command_type: string;
  arguments: Record<string, unknown>;
  summary: string;
  consequential: boolean;
  status: "waiting" | "running" | "completed" | "failed" | "skipped";
  error_code: string | null;
  result_reference: string | null;
};

type ActionPlan = {
  id: number;
  transformation_run_id: number | null;
  explanation: string;
  plan_hash: string;
  plan_version: number;
  requires_confirmation: boolean;
  status: string;
  steps: PlanStep[];
};

type ChatState = { messages: ChatMessage[]; plans: ActionPlan[] };
type SourceMode = "paste" | "upload" | "url" | null;

function isMessage(value: unknown): value is ChatMessage {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    (value.role === "user" || value.role === "assistant") &&
    typeof value.content === "string" &&
    (typeof value.action_plan_id === "number" || value.action_plan_id === null)
  );
}

function isStep(value: unknown): value is PlanStep {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.ordinal === "number" &&
    typeof value.command_type === "string" &&
    isRecord(value.arguments) &&
    typeof value.summary === "string" &&
    typeof value.consequential === "boolean" &&
    ["waiting", "running", "completed", "failed", "skipped"].includes(
      String(value.status),
    ) &&
    (typeof value.error_code === "string" || value.error_code === null) &&
    (typeof value.result_reference === "string" ||
      value.result_reference === null)
  );
}

function isPlan(value: unknown): value is ActionPlan {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    (typeof value.transformation_run_id === "number" ||
      value.transformation_run_id === null) &&
    typeof value.explanation === "string" &&
    typeof value.plan_hash === "string" &&
    typeof value.plan_version === "number" &&
    typeof value.requires_confirmation === "boolean" &&
    typeof value.status === "string" &&
    Array.isArray(value.steps) &&
    value.steps.every(isStep)
  );
}

function isChatState(value: unknown): value is ChatState {
  return (
    isRecord(value) &&
    Array.isArray(value.messages) &&
    value.messages.every(isMessage) &&
    Array.isArray(value.plans) &&
    value.plans.every(isPlan)
  );
}

function safeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "The workspace changed. Ask Weave to prepare a fresh plan.";
  }
  if (error instanceof ApiError && error.status === 429) {
    return "Weave is busy right now. Wait a moment and try again.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return "We need a little more detail before this can be planned.";
  }
  return "Weave could not complete that request. Your workspace controls are still available.";
}

function outputNames(arguments_: Record<string, unknown>): string[] {
  const request = arguments_.request;
  if (!isRecord(request) || !Array.isArray(request.output_types)) return [];
  return request.output_types.flatMap((value) => {
    const item = OUTPUT_TYPES.find((output) => output.value === value);
    return item ? [item.label] : [];
  });
}

export function WeaveAssistant({
  transformationId,
  contextLabel,
  creationMode,
  onNavigateNew,
  onTransformationCreated,
  onWorkspaceChanged,
}: {
  transformationId: number | null;
  contextLabel: string;
  creationMode: boolean;
  onNavigateNew: () => void;
  onTransformationCreated: (
    id: number,
    title: string,
    sourceVersion: number,
  ) => void;
  onWorkspaceChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ChatState>({ messages: [], plans: [] });
  const [message, setMessage] = useState("");
  const [sourceDraft, setSourceDraft] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const body =
        transformationId === null
          ? await api.weaveChat()
          : await api.chatWorkspace(transformationId);
      if (isChatState(body)) setState(body);
      else throw new Error("invalid chat response");
      setError(null);
    } catch {
      setError(
        "Conversation history could not be loaded. Try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  }, [transformationId]);

  useEffect(() => {
    if (creationMode) setOpen(true);
  }, [creationMode]);

  useEffect(() => {
    if (open) {
      void refresh();
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }, [open, refresh]);

  useEffect(() => {
    if (transformationId === null) return;
    setSourceDraft("");
    setSourceName("");
    setSourceMode(null);
    setSourceUrl("");
  }, [transformationId]);

  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        launcherRef.current?.focus();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  useEffect(() => {
    if (!open || !panelRef.current) return;
    const history = panelRef.current.querySelector<HTMLElement>(
      ".weave-panel__history",
    );
    if (history) history.scrollTop = history.scrollHeight;
  }, [open, state.messages, busy, sourceMode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busy) return;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      if (transformationId === null) {
        await api.proposeWeaveActionPlan(request, sourceDraft || undefined);
      } else {
        await api.proposeActionPlan(transformationId, request);
      }
      await refresh();
      setSourceMode(null);
    } catch (submitError) {
      setError(safeError(submitError));
      setMessage(request);
    } finally {
      setBusy(false);
      composerRef.current?.focus();
    }
  }

  async function decide(plan: ActionPlan, decision: "confirm" | "reject") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result =
        decision === "confirm"
          ? await api.confirmActionPlan(
              plan.id,
              plan.plan_hash,
              plan.plan_version,
            )
          : await api.rejectActionPlan(
              plan.id,
              plan.plan_hash,
              plan.plan_version,
            );
      if (!isPlan(result)) throw new Error("invalid plan response");
      await refresh();
      const createStep = result.steps.find(
        (step) =>
          step.command_type === "create_transformation" &&
          step.status === "completed",
      );
      const createdId = createStep?.result_reference?.match(
        /^transformation_run_id:(\d+)$/,
      )?.[1];
      if (decision === "confirm" && createStep && createdId) {
        const request = createStep.arguments.request;
        const source = isRecord(request) ? request.source_text : "";
        const title =
          typeof source === "string"
            ? deriveTransformationTitle(source)
            : "New transformation";
        onTransformationCreated(Number(createdId), title, 1);
      } else if (
        decision === "confirm" &&
        result.status === "completed" &&
        transformationId !== null
      ) {
        onWorkspaceChanged();
      }
    } catch (decisionError) {
      setError(safeError(decisionError));
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function extractFile(file: File | undefined) {
    if (!file) return;
    setSourceError(null);
    setBusy(true);
    try {
      const body = await api.extractTextFile(file);
      if (!isExtractedText(body)) throw new Error("invalid extraction");
      if (body.source_text.length > 20_000) {
        setSourceError("This source is over the 20,000 character limit.");
        return;
      }
      setSourceDraft(body.source_text);
      setSourceName(body.filename);
      setSourceMode(null);
    } catch {
      setSourceError("This document could not be read. Try another file.");
    } finally {
      setBusy(false);
    }
  }

  async function importUrl() {
    if (!sourceUrl.trim()) return;
    setSourceError(null);
    setBusy(true);
    try {
      const body = await api.extractUrl(sourceUrl);
      if (
        !isRecord(body) ||
        typeof body.source_text !== "string" ||
        typeof body.title !== "string"
      ) {
        throw new Error("invalid import");
      }
      if (body.source_text.length > 20_000) {
        setSourceError("This source is over the 20,000 character limit.");
        return;
      }
      setSourceDraft(body.source_text);
      setSourceName("Imported page: " + body.title);
      setSourceMode(null);
    } catch {
      setSourceError(
        "This page could not be imported. Check the address and retry.",
      );
    } finally {
      setBusy(false);
    }
  }

  function clearDraft() {
    setMessage("");
    setSourceDraft("");
    setSourceName("");
    setSourceUrl("");
    setSourceMode(null);
    setSourceError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const plansById = new Map(state.plans.map((plan) => [plan.id, plan]));
  const suggestions =
    creationMode || transformationId === null
      ? [
          "Create an executive summary and presentation",
          "What can AxiomWeave create?",
        ]
      : contextLabel === "Project overview"
        ? ["Generate selected artifacts", "Explain the supported outputs"]
        : /infographic/i.test(contextLabel)
          ? ["Render this infographic", "Check its evidence"]
          : /video/i.test(contextLabel)
            ? ["Render this video package", "Retry the failed scene"]
            : [
                "Regenerate this artifact",
                "Check its evidence",
                "Update from the latest source",
              ];
  const placeholder = creationMode
    ? "Describe what you want to create from your source…"
    : transformationId === null
      ? "What do you want to create?"
      : /Executive Summary|Post|Advisory|Presentation|Infographic|Video/i.test(
            contextLabel,
          )
        ? "Ask about or modify this artifact…"
        : "Ask Weave to update, regenerate or review this workspace…";

  return (
    <>
      {open && (
        <>
          <button
            type="button"
            className="weave-panel-scrim"
            aria-label="Close Weave assistant"
            onClick={() => {
              setOpen(false);
              launcherRef.current?.focus();
            }}
          />
          <section
            className="weave-panel"
            id="weave-panel"
            aria-label="Weave assistant"
            aria-modal="false"
            role="dialog"
            ref={panelRef}
          >
            <header className="weave-panel__header">
              <div className="weave-panel__identity">
                <span className="weave-panel__mark" aria-hidden="true">
                  <MessageCircle />
                </span>
                <div>
                  <strong>Weave</strong>
                  <span>AxiomWeave assistant</span>
                  <small>{contextLabel}</small>
                </div>
              </div>
              <div className="weave-panel__controls">
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Clear message and source draft"
                  title="Clear draft"
                  onClick={clearDraft}
                >
                  <span className="weave-panel__clear-label">Clear draft</span>
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Minimize Weave assistant"
                  onClick={() => {
                    setOpen(false);
                    launcherRef.current?.focus();
                  }}
                >
                  <Minus aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close Weave assistant"
                  onClick={() => {
                    setOpen(false);
                    launcherRef.current?.focus();
                  }}
                >
                  <X aria-hidden="true" />
                </button>
              </div>
            </header>
            <div className="weave-panel__history" aria-live="polite">
              {loading ? (
                <p className="weave-panel__loading" role="status">
                  <LoaderCircle className="status-spin" aria-hidden="true" />
                  Opening your conversation…
                </p>
              ) : state.messages.length === 0 ? (
                <div className="weave-welcome">
                  <p className="weave-welcome__label">Weave</p>
                  <p>
                    {creationMode
                      ? "Tell me about your source and what you want to make. You can add a document or paste the source here."
                      : transformationId === null
                        ? "What would you like to create? I can help shape a source into clear, useful materials."
                        : contextLabel === "Project overview"
                          ? "Your transformation is ready. What would you like Weave to do next?"
                          : `What would you like to do with ${contextLabel}?`}
                  </p>
                  {suggestions.length > 0 && (
                    <div className="weave-suggestions" aria-label="Suggestions">
                      {suggestions.map((item) => (
                        <button
                          type="button"
                          key={item}
                          onClick={() => {
                            if (item === "Create a transformation") {
                              onNavigateNew();
                              return;
                            }
                            setMessage(item);
                            composerRef.current?.focus();
                          }}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  )}
                  {transformationId === null && !creationMode && (
                    <button
                      type="button"
                      className="weave-link-button"
                      onClick={onNavigateNew}
                    >
                      Open creation setup
                    </button>
                  )}
                </div>
              ) : (
                state.messages.map((item) => {
                  const plan =
                    item.action_plan_id === null
                      ? undefined
                      : plansById.get(item.action_plan_id);
                  return (
                    <article
                      className={`weave-message weave-message--${item.role}`}
                      key={item.id}
                    >
                      <strong>{item.role === "user" ? "You" : "Weave"}</strong>
                      <p>{item.content}</p>
                      {item.role === "assistant" &&
                        plan &&
                        plan.steps.length > 0 && (
                          <PlanCard plan={plan} busy={busy} onDecide={decide} />
                        )}
                    </article>
                  );
                })
              )}
            </div>
            {error && (
              <p className="weave-panel__error" role="alert">
                {error}
              </p>
            )}
            {transformationId === null && (
              <div className="weave-source">
                {sourceName && (
                  <div className="weave-source__attached" role="status">
                    <FileUp aria-hidden="true" />
                    <span>{sourceName}</span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Remove source"
                      onClick={() => {
                        setSourceDraft("");
                        setSourceName("");
                      }}
                    >
                      <X aria-hidden="true" />
                    </button>
                  </div>
                )}
                {sourceMode === "paste" && (
                  <label className="weave-source__paste">
                    <span>Paste your source</span>
                    <textarea
                      rows={5}
                      maxLength={20_000}
                      value={sourceDraft}
                      onChange={(event) => {
                        setSourceDraft(event.target.value);
                        setSourceName("Pasted source");
                      }}
                      placeholder="Paste a report, announcement or policy…"
                    />
                  </label>
                )}
                {sourceMode === "url" && (
                  <div className="weave-source__url">
                    <label htmlFor="weave-source-url">Public page URL</label>
                    <div>
                      <input
                        id="weave-source-url"
                        type="url"
                        value={sourceUrl}
                        onChange={(event) => setSourceUrl(event.target.value)}
                        placeholder="https://example.com/report"
                      />
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={busy || !sourceUrl.trim()}
                        onClick={() => void importUrl()}
                      >
                        Import
                      </button>
                    </div>
                  </div>
                )}
                {sourceError && (
                  <p className="weave-source__error" role="alert">
                    {sourceError}
                  </p>
                )}
                <input
                  ref={fileInputRef}
                  className="visually-hidden"
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.rtf,.png,.jpg,.jpeg,.webp"
                  aria-label="Upload a source document"
                  onChange={(event) =>
                    void extractFile(event.currentTarget.files?.[0])
                  }
                />
              </div>
            )}
            <form
              className="weave-composer"
              onSubmit={(event) => void submit(event)}
            >
              {transformationId === null && (
                <div className="weave-composer__attachments">
                  <button
                    type="button"
                    aria-label="Add a source"
                    aria-expanded={sourceMode !== null}
                    onClick={() =>
                      setSourceMode((current) => (current ? null : "paste"))
                    }
                  >
                    <Paperclip aria-hidden="true" />
                    Add source
                  </button>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <FileUp aria-hidden="true" />
                    Upload
                  </button>
                  <button type="button" onClick={() => setSourceMode("url")}>
                    <Link2 aria-hidden="true" />
                    Import URL
                  </button>
                </div>
              )}
              <label className="visually-hidden" htmlFor="weave-message">
                Message Weave
              </label>
              <div className="weave-composer__input">
                <textarea
                  id="weave-message"
                  ref={composerRef}
                  value={message}
                  maxLength={2_000}
                  rows={3}
                  placeholder={placeholder}
                  onChange={(event) => setMessage(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      (event.ctrlKey || event.metaKey)
                    ) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                />
                <button
                  type="submit"
                  aria-label="Send message"
                  disabled={busy || !message.trim()}
                >
                  {busy ? (
                    <LoaderCircle className="status-spin" aria-hidden="true" />
                  ) : (
                    <Send aria-hidden="true" />
                  )}
                </button>
              </div>
              <small>Enter a request; use Ctrl+Enter to send.</small>
            </form>
          </section>
        </>
      )}
      <button
        type="button"
        className="weave-launcher"
        aria-label={open ? "Close Weave assistant" : "Open Weave assistant"}
        aria-controls="weave-panel"
        aria-expanded={open}
        ref={launcherRef}
        onClick={() => setOpen((value) => !value)}
      >
        <MessageCircle aria-hidden="true" />
        <span>Weave</span>
      </button>
    </>
  );
}

function PlanCard({
  plan,
  busy,
  onDecide,
}: {
  plan: ActionPlan;
  busy: boolean;
  onDecide: (plan: ActionPlan, decision: "confirm" | "reject") => Promise<void>;
}) {
  return (
    <section className="weave-plan" aria-label="Weave proposal">
      <div className="weave-plan__heading">
        <div>
          <span>Weave proposes</span>
          <strong>
            {plan.steps.length === 1
              ? plan.steps[0].summary
              : `Plan · ${plan.steps.length} actions`}
          </strong>
        </div>
        {plan.status === "awaiting_confirmation" && (
          <span className="weave-plan__pending">Review</span>
        )}
      </div>
      {plan.steps.map((step) => {
        const request = isRecord(step.arguments.request)
          ? step.arguments.request
          : null;
        return (
          <div className="weave-plan__step" key={step.id}>
            <span className="weave-plan__step-icon" aria-hidden="true">
              {step.status === "completed" ? <Check /> : step.ordinal}
            </span>
            <div>
              <strong>{step.summary}</strong>
              {step.command_type === "create_transformation" && (
                <ul className="weave-plan__details">
                  {outputNames(step.arguments).length > 0 && (
                    <li>Outputs: {outputNames(step.arguments).join(", ")}</li>
                  )}
                  {request &&
                    ["audience", "tone", "objective", "style"].map((field) => {
                      const value = request[field];
                      return typeof value === "string" && value ? (
                        <li key={field}>
                          {field[0].toUpperCase() + field.slice(1)}: {value}
                        </li>
                      ) : null;
                    })}
                  {request && typeof request.source_text === "string" && (
                    <li>
                      Source: {request.source_text.length.toLocaleString()}{" "}
                      characters
                    </li>
                  )}
                </ul>
              )}
              {step.error_code && (
                <small>
                  {step.error_code === "command_failed"
                    ? "This action could not be completed. Try preparing a new plan."
                    : "This action needs attention before it can be completed."}
                </small>
              )}
            </div>
          </div>
        );
      })}
      {plan.status === "awaiting_confirmation" &&
        plan.requires_confirmation && (
          <div className="weave-plan__actions">
            <button
              type="button"
              className="button-secondary"
              disabled={busy}
              onClick={() => void onDecide(plan, "reject")}
            >
              Cancel
            </button>
            <button
              type="button"
              className="button-primary"
              disabled={busy}
              onClick={() => void onDecide(plan, "confirm")}
            >
              Confirm
            </button>
          </div>
        )}
      {plan.status === "completed" && (
        <p className="weave-plan__complete">
          Completed after your confirmation.
        </p>
      )}
    </section>
  );
}
