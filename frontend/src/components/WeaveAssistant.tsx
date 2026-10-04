import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Check,
  ChevronLeft,
  Ellipsis,
  FileUp,
  Link2,
  LoaderCircle,
  Menu,
  MessageCircle,
  Minus,
  Paperclip,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { ApiError, api } from "../api";
import { OUTPUT_TYPES, type OutputType } from "../types";
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
  target_ids?: Record<string, number>;
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
      value.result_reference === null) &&
    (value.target_ids === undefined ||
      (isRecord(value.target_ids) &&
        Object.values(value.target_ids).every(
          (item) => typeof item === "number",
        )))
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
  return "Weave couldn't prepare that setup. Try again.";
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
  creationPage = false,
  creationSessionId = 0,
  onExitCreationPage = () => {},
  onManualSetup = () => {},
  onToggleNavigation = () => {},
  onNavigateNew,
  onTransformationCreated,
  onWorkspaceChanged,
}: {
  transformationId: number | null;
  contextLabel: string;
  creationMode: boolean;
  creationPage?: boolean;
  creationSessionId?: number;
  onExitCreationPage?: () => void;
  onManualSetup?: () => void;
  onToggleNavigation?: () => void;
  onNavigateNew: () => void;
  onTransformationCreated: (
    id: number,
    title: string,
    sourceVersion: number,
    outputType?: OutputType,
    notice?: string,
  ) => void;
  onWorkspaceChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ChatState>({ messages: [], plans: [] });
  const [sourceLabelsByPlanId, setSourceLabelsByPlanId] = useState<
    Record<number, string>
  >({});
  const [message, setMessage] = useState("");
  const [sourceDraft, setSourceDraft] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>(null);
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const [sourceUrl, setSourceUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const busyRef = useRef(false);
  const creationSessionRef = useRef<number | null>(null);
  const creationHistoryCutoffRef = useRef(0);
  const visible = creationPage || open;

  const refresh = useCallback(
    async (showLoading = true) => {
      if (showLoading) setLoading(true);
      try {
        const body =
          transformationId === null
            ? await api.weaveChat()
            : await api.chatWorkspace(transformationId);
        if (!isChatState(body)) throw new Error("invalid chat response");
        let messages = body.messages;
        if (creationPage && transformationId === null) {
          if (creationSessionRef.current !== creationSessionId) {
            creationSessionRef.current = creationSessionId;
            creationHistoryCutoffRef.current = Math.max(
              0,
              ...body.messages.map((item) => item.id),
            );
          }
          messages = body.messages.filter(
            (item) => item.id > creationHistoryCutoffRef.current,
          );
        }
        const visiblePlanIds = new Set(
          messages.flatMap((item) =>
            item.action_plan_id === null ? [] : [item.action_plan_id],
          ),
        );
        setState({
          messages,
          plans: body.plans.filter((plan) => visiblePlanIds.has(plan.id)),
        });
        setError(null);
      } catch {
        setError(
          "Conversation history could not be loaded. Try again in a moment.",
        );
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [creationPage, creationSessionId, transformationId],
  );

  useEffect(() => {
    if (visible) {
      void refresh();
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }, [visible, refresh]);

  useEffect(() => {
    if (transformationId === null) return;
    setSourceDraft("");
    setSourceName("");
    setSourceMode(null);
    setSourceUrl("");
  }, [transformationId]);

  useEffect(() => {
    if (!creationPage) return;
    setOpen(false);
    setMessage("");
    setSourceDraft("");
    setSourceName("");
    setSourceMode(null);
    setSourceMenuOpen(false);
    setSourceUrl("");
    setSourceError(null);
  }, [creationPage, creationSessionId]);

  useEffect(() => {
    if (!visible) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && creationPage) {
        onExitCreationPage();
      } else if (event.key === "Escape") {
        setOpen(false);
        launcherRef.current?.focus();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [visible, creationPage, onExitCreationPage]);

  useEffect(() => {
    if (!visible || !panelRef.current) return;
    const history = panelRef.current.querySelector<HTMLElement>(
      ".weave-panel__history",
    );
    if (history) history.scrollTop = history.scrollHeight;
  }, [visible, state.messages, busy, planning, sourceMode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busyRef.current || loading) return;
    busyRef.current = true;
    setBusy(true);
    setPlanning(true);
    setError(null);
    setMessage("");
    const optimisticId = -Date.now();
    setState((current) => ({
      ...current,
      messages: [
        ...current.messages,
        {
          id: optimisticId,
          role: "user",
          content: request,
          action_plan_id: null,
        },
      ],
    }));
    try {
      let proposedPlan: unknown;
      if (transformationId === null) {
        proposedPlan = await api.proposeWeaveActionPlan(
          request,
          sourceDraft || undefined,
        );
      } else {
        proposedPlan = await api.proposeActionPlan(transformationId, request);
      }
      const sourceLabel = sourceName || (sourceDraft ? "Pasted source" : null);
      if (transformationId === null && sourceLabel && isPlan(proposedPlan)) {
        setSourceLabelsByPlanId((current) => ({
          ...current,
          [proposedPlan.id]: sourceLabel,
        }));
      }
      await refresh(false);
      setSourceMode(null);
      setSourceMenuOpen(false);
    } catch (submitError) {
      setState((current) => ({
        ...current,
        messages: current.messages.filter((item) => item.id !== optimisticId),
      }));
      await refresh(false);
      setError(safeError(submitError));
      setMessage(request);
    } finally {
      busyRef.current = false;
      setBusy(false);
      setPlanning(false);
      composerRef.current?.focus();
    }
  }

  async function decide(plan: ActionPlan, decision: "confirm" | "reject") {
    if (busyRef.current) return;
    busyRef.current = true;
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
      await refresh(false);
      const createStep = result.steps.find(
        (step) =>
          step.command_type === "create_transformation_and_generate" &&
          step.status === "completed",
      );
      const createdId =
        createStep?.target_ids?.transformation_run_id ??
        Number(
          createStep?.result_reference?.match(
            /transformation_run_id:(\d+)/,
          )?.[1],
        );
      if (decision === "confirm" && createStep && createdId) {
        const request = createStep.arguments.request;
        const source = isRecord(request) ? request.source_text : "";
        const selected =
          isRecord(request) && Array.isArray(request.output_types)
            ? request.output_types
            : [];
        const initialOutput = OUTPUT_TYPES.find((output) =>
          selected.includes(output.value),
        )?.value;
        const sourceVersionCandidate =
          createStep.target_ids?.source_version_number ??
          Number(
            createStep.result_reference?.match(
              /source_version_number:(\d+)/,
            )?.[1],
          );
        const generationFailed = createStep.result_reference?.includes(
          "generation_status:failed",
        );
        const title =
          typeof source === "string"
            ? deriveTransformationTitle(source)
            : "New transformation";
        onTransformationCreated(
          Number(createdId),
          title,
          Number.isInteger(sourceVersionCandidate) && sourceVersionCandidate > 0
            ? sourceVersionCandidate
            : 1,
          initialOutput,
          generationFailed
            ? "Transformation created, but artifact generation could not be queued. Ask Weave to retry generation."
            : undefined,
        );
      } else if (
        decision === "confirm" &&
        result.status === "completed" &&
        transformationId !== null
      ) {
        onWorkspaceChanged();
      }
    } catch (decisionError) {
      setError(safeError(decisionError));
      await refresh(false);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function extractFile(file: File | undefined) {
    if (!file || busyRef.current) return;
    busyRef.current = true;
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
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function importUrl() {
    if (!sourceUrl.trim() || busyRef.current) return;
    busyRef.current = true;
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
      busyRef.current = false;
      setBusy(false);
    }
  }

  function clearDraft() {
    setMessage("");
    setSourceDraft("");
    setSourceName("");
    setSourceUrl("");
    setSourceMode(null);
    setSourceMenuOpen(false);
    setSourceError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const plansById = new Map(state.plans.map((plan) => [plan.id, plan]));
  const suggestions = creationMode
    ? [
        "Create an infographic",
        "Make a presentation and summary",
        "Turn a report into social posts",
      ]
    : transformationId === null
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
  const placeholder = creationPage
    ? "Describe what you want to create from your source…"
    : transformationId === null
      ? "What do you want to create?"
      : /Executive Summary|Post|Advisory|Presentation|Infographic|Video/i.test(
            contextLabel,
          )
        ? "Ask about or modify this artifact…"
        : "Ask Weave to update, regenerate or review this workspace…";

  const composerPlaceholder = creationPage
    ? "Ask Weave what you want to create..."
    : placeholder;
  const attachedSourceLabel = sourceDraft.trim()
    ? `${sourceName || "Pasted source"} · ${sourceDraft.length.toLocaleString()} characters`
    : "";

  return (
    <>
      {visible && (
        <>
          {!creationPage && (
            <button
              type="button"
              className="weave-panel-scrim"
              aria-label="Close Weave assistant"
              onClick={() => {
                setOpen(false);
                launcherRef.current?.focus();
              }}
            />
          )}
          <section
            className={
              "weave-panel" +
              (creationPage ? " weave-panel--creation-page" : "")
            }
            id="weave-panel"
            aria-label="Weave assistant"
            aria-modal={creationPage ? undefined : "false"}
            role={creationPage ? "region" : "dialog"}
            ref={panelRef}
          >
            <header className="weave-panel__header">
              {creationPage ? (
                <div className="weave-creation-heading">
                  <button
                    type="button"
                    className="icon-button weave-creation-heading__menu"
                    aria-label="Open navigation menu"
                    onClick={onToggleNavigation}
                  >
                    <Menu aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="icon-button weave-creation-heading__back"
                    aria-label="Back to start options"
                    onClick={onExitCreationPage}
                  >
                    <ChevronLeft aria-hidden="true" />
                  </button>
                  <div>
                    <strong id="weave-panel-title">New transformation</strong>
                    <span>Weave · Creating a transformation</span>
                  </div>
                </div>
              ) : (
                <div className="weave-panel__identity">
                  <span className="weave-panel__mark" aria-hidden="true">
                    <MessageCircle />
                  </span>
                  <div>
                    <strong id="weave-panel-title">Weave</strong>
                    <span>AxiomWeave assistant</span>
                    <small>{contextLabel}</small>
                  </div>
                </div>
              )}
              <div className="weave-panel__controls">
                <details className="weave-panel__overflow">
                  <summary
                    role="button"
                    className="icon-button"
                    aria-label="More Weave actions"
                  >
                    <Ellipsis aria-hidden="true" />
                  </summary>
                  <div className="weave-panel__overflow-menu">
                    <button type="button" onClick={clearDraft}>
                      Reset draft
                    </button>
                  </div>
                </details>
                {creationPage ? (
                  <button
                    type="button"
                    className="button-secondary weave-creation-manual"
                    onClick={onManualSetup}
                  >
                    Manual setup
                  </button>
                ) : (
                  <>
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
                  </>
                )}
              </div>
            </header>
            <div className="weave-panel__history" aria-live="polite">
              {loading ? (
                <p className="weave-panel__loading" role="status">
                  <LoaderCircle className="status-spin" aria-hidden="true" />
                  Opening your conversation…
                </p>
              ) : state.messages.length === 0 ? (
                <div
                  className={
                    "weave-welcome" +
                    (creationPage ? " weave-welcome--creation" : "")
                  }
                >
                  {creationPage ? (
                    <>
                      <span className="weave-welcome__mark" aria-hidden="true">
                        <Sparkles />
                      </span>
                      <h2>What do you want to create?</h2>
                      <p>Add your source and tell me what outputs you need.</p>
                    </>
                  ) : (
                    <>
                      <p className="weave-welcome__label">Weave</p>
                      <p>
                        {transformationId === null
                          ? "What would you like to create? I can help shape a source into clear, useful materials."
                          : contextLabel === "Project overview"
                            ? "Your transformation is ready. What would you like Weave to do next?"
                            : `What would you like to do with ${contextLabel}?`}
                      </p>
                    </>
                  )}
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
                          <PlanCard
                            plan={plan}
                            busy={busy}
                            sourceLabel={sourceLabelsByPlanId[plan.id] ?? null}
                            draftSource={sourceDraft}
                            onDecide={decide}
                          />
                        )}
                    </article>
                  );
                })
              )}
              {planning && (
                <p className="weave-thinking" role="status">
                  <LoaderCircle className="status-spin" aria-hidden="true" />
                  Weave is preparing your setup...
                </p>
              )}
            </div>
            {error && (
              <p className="weave-panel__error" role="alert">
                {error}
              </p>
            )}
            {transformationId === null && (
              <div className="weave-source">
                {attachedSourceLabel && (
                  <div className="weave-source__attached" role="status">
                    <FileUp aria-hidden="true" />
                    <span>{attachedSourceLabel}</span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Remove source"
                      disabled={busy}
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
                <>
                  <div className="weave-composer__attachments">
                    <button
                      type="button"
                      aria-label="Add a source"
                      aria-expanded={sourceMenuOpen}
                      disabled={busy}
                      onClick={() => {
                        setSourceMode(null);
                        setSourceMenuOpen((current) => !current);
                      }}
                    >
                      <Plus aria-hidden="true" />
                      Add source
                    </button>
                  </div>
                  {sourceMenuOpen && (
                    <div
                      className="weave-source-menu"
                      aria-label="Source options"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setSourceMenuOpen(false);
                          fileInputRef.current?.click();
                        }}
                      >
                        <FileUp aria-hidden="true" /> Upload source
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSourceMenuOpen(false);
                          setSourceMode("paste");
                        }}
                      >
                        <Paperclip aria-hidden="true" /> Paste source
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSourceMenuOpen(false);
                          setSourceMode("url");
                        }}
                      >
                        <Link2 aria-hidden="true" /> Import public URL
                      </button>
                    </div>
                  )}
                </>
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
                  placeholder={composerPlaceholder}
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
                  disabled={busy || loading || !message.trim()}
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
      {!creationPage && (
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
      )}
    </>
  );
}

function PlanCard({
  plan,
  busy,
  sourceLabel,
  draftSource,
  onDecide,
}: {
  plan: ActionPlan;
  busy: boolean;
  sourceLabel: string | null;
  draftSource: string;
  onDecide: (plan: ActionPlan, decision: "confirm" | "reject") => Promise<void>;
}) {
  const createsTransformation = plan.steps.some(
    (step) => step.command_type === "create_transformation_and_generate",
  );
  const plannedRequest = createsTransformation
    ? plan.steps.find(
        (step) => step.command_type === "create_transformation_and_generate",
      )?.arguments.request
    : undefined;
  const sourceChanged =
    isRecord(plannedRequest) &&
    typeof plannedRequest.source_text === "string" &&
    plannedRequest.source_text !== draftSource;
  return (
    <section className="weave-plan" aria-label="Weave proposal">
      <div className="weave-plan__heading">
        <div>
          <span>Weave proposes</span>
          <strong>
            {createsTransformation
              ? "Ready to create"
              : plan.steps.length === 1
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
              <strong className="weave-plan__summary">{step.summary}</strong>
              {step.command_type === "create_transformation_and_generate" && (
                <ul className="weave-plan__details">
                  {outputNames(step.arguments).length > 0 && (
                    <li>Generate: {outputNames(step.arguments).join(", ")}</li>
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
                      Source: {sourceLabel ? `${sourceLabel} · ` : ""}
                      {request.source_text.length.toLocaleString()} characters
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
            {sourceChanged && (
              <p className="weave-plan__source-changed" role="status">
                The source draft changed. Prepare a new proposal to use the
                updated source.
              </p>
            )}
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
              disabled={busy || sourceChanged}
              onClick={() => void onDecide(plan, "confirm")}
            >
              {createsTransformation ? "Create and generate" : "Confirm"}
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
