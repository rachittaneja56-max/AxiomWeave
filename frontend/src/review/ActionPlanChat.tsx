import { useEffect, useState, type FormEvent } from "react";
import { Check, LoaderCircle, MessageCircle, X } from "lucide-react";
import { ApiError, api } from "../api";
import { isRecord } from "../utils";

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
  summary: string;
  consequential: boolean;
  status: "waiting" | "running" | "completed" | "failed" | "skipped";
  error_code: string | null;
  result_reference: string | null;
};

type ActionPlan = {
  id: number;
  explanation: string;
  plan_hash: string;
  plan_version: number;
  requires_confirmation: boolean;
  status: string;
  steps: PlanStep[];
};

type ChatState = {
  messages: ChatMessage[];
  plans: ActionPlan[];
};

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

function isApiPlan(value: unknown): value is ActionPlan {
  return isPlan(value);
}

function safeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "The workspace changed. Review the latest state and create a new plan.";
  }
  if (error instanceof ApiError && error.status === 429) {
    return "Chat is busy right now. Wait a moment and try again.";
  }
  return "Chat could not complete that request. You can continue with the manual controls.";
}

export function ActionPlanChat({
  transformationId,
}: {
  transformationId: number;
}) {
  const [state, setState] = useState<ChatState>({ messages: [], plans: [] });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const body = await api.chatWorkspace(transformationId);
      if (isChatState(body)) setState(body);
    } catch {
      setError(
        "Chat history could not be loaded. Manual controls are available.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // The workspace ID scopes chat history; refresh after an explicit action only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transformationId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busy) return;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const proposed = await api.proposeActionPlan(transformationId, request);
      if (!isApiPlan(proposed)) throw new Error("invalid plan response");
      await refresh();
    } catch (submitError) {
      setError(safeError(submitError));
      setMessage(request);
    } finally {
      setBusy(false);
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
      if (!isApiPlan(result)) throw new Error("invalid plan response");
      await refresh();
    } catch (decisionError) {
      setError(safeError(decisionError));
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const plansById = new Map(state.plans.map((plan) => [plan.id, plan]));

  return (
    <section className="action-chat" aria-labelledby="action-chat-title">
      <header className="action-chat__heading">
        <div>
          <p className="eyebrow">Workspace assistant</p>
          <h2 id="action-chat-title">
            <MessageCircle aria-hidden="true" /> Chat actions
          </h2>
          <p>
            Chat proposes bounded actions. Durable changes wait for your
            confirmation.
          </p>
        </div>
      </header>
      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
      <div className="action-chat__history" aria-live="polite">
        {loading ? (
          <p className="action-chat__empty" role="status">
            <LoaderCircle className="status-spin" aria-hidden="true" /> Loading
            chat…
          </p>
        ) : state.messages.length === 0 ? (
          <p className="action-chat__empty">
            Ask for a workspace action, such as generating selected artifacts or
            reviewing a version.
          </p>
        ) : (
          state.messages.map((item) => (
            <article
              className={`action-chat__message action-chat__message--${item.role}`}
              key={item.id}
            >
              <strong>{item.role === "user" ? "You" : "Assistant"}</strong>
              <p>{item.content}</p>
              {item.role === "assistant" &&
                item.action_plan_id !== null &&
                plansById.has(item.action_plan_id) && (
                  <PlanCard
                    plan={plansById.get(item.action_plan_id)!}
                    busy={busy}
                    onDecide={decide}
                  />
                )}
            </article>
          ))
        )}
      </div>
      <form
        className="action-chat__form"
        onSubmit={(event) => void submit(event)}
      >
        <label htmlFor="action-chat-input">Describe what you want to do</label>
        <textarea
          id="action-chat-input"
          value={message}
          maxLength={2_000}
          rows={3}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="For example: regenerate the presentation"
        />
        <div className="action-chat__form-footer">
          <span>
            Your request is checked against this workspace before a plan
            appears.
          </span>
          <button
            className="button-primary"
            type="submit"
            disabled={busy || !message.trim()}
          >
            {busy ? (
              <LoaderCircle className="status-spin" aria-hidden="true" />
            ) : null}
            Propose action
          </button>
        </div>
      </form>
    </section>
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
    <section className="action-plan-card" aria-label={`Action plan ${plan.id}`}>
      <div className="action-plan-card__topline">
        <h3>What will happen</h3>
        <span
          className={`action-plan-status action-plan-status--${plan.status}`}
        >
          {plan.status.replaceAll("_", " ")}
        </span>
      </div>
      <p>{plan.explanation}</p>
      {plan.steps.length === 0 ? (
        <p className="action-chat__empty">
          No mutation was proposed. Clarify the target or use the manual
          controls.
        </p>
      ) : (
        <ol className="action-plan-steps">
          {plan.steps.map((step) => (
            <li key={step.id}>
              <span
                className={`action-plan-step-state action-plan-step-state--${step.status}`}
              >
                {step.status === "completed" ? (
                  <Check aria-label="Completed" role="img" />
                ) : step.status === "failed" || step.status === "skipped" ? (
                  <X aria-label={step.status} role="img" />
                ) : step.status === "running" ? (
                  <LoaderCircle
                    className="status-spin"
                    aria-label="Running"
                    role="img"
                  />
                ) : (
                  step.ordinal
                )}
              </span>
              <span>
                <strong>{step.summary}</strong>
                {step.consequential && (
                  <small>Changes workspace state or starts provider work</small>
                )}
                {step.error_code && (
                  <small>Could not complete: {step.error_code}</small>
                )}
                {step.result_reference && (
                  <small>Result: {step.result_reference}</small>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
      {plan.requires_confirmation &&
        plan.status === "awaiting_confirmation" && (
          <div className="action-plan-card__actions">
            <button
              className="button-secondary"
              type="button"
              disabled={busy}
              onClick={() => void onDecide(plan, "reject")}
            >
              Cancel
            </button>
            <button
              className="button-primary"
              type="button"
              disabled={busy}
              onClick={() => void onDecide(plan, "confirm")}
            >
              Confirm plan
            </button>
          </div>
        )}
    </section>
  );
}
