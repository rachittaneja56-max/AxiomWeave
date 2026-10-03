import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionPlanChat } from "./review/ActionPlanChat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const plan = {
  id: 9,
  explanation: "Generate the selected artifact family.",
  plan_hash: "a".repeat(64),
  plan_version: 1,
  requires_confirmation: true,
  status: "awaiting_confirmation",
  steps: [
    {
      id: 11,
      ordinal: 1,
      command_type: "generate_selected_artifacts",
      summary: "Generate the executive summary",
      consequential: true,
      status: "waiting",
      error_code: null,
      result_reference: null,
    },
  ],
};

describe("ActionPlanChat", () => {
  it("proposes a plan without executing it, then confirms the exact plan explicitly", async () => {
    let hasPlan = false;
    let isConfirmed = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/transformations/4/chat" && !init?.method) {
        const currentPlan = isConfirmed
          ? {
              ...plan,
              status: "completed",
              steps: plan.steps.map((step) => ({
                ...step,
                status: "completed",
              })),
            }
          : plan;
        return Promise.resolve(
          response(
            hasPlan
              ? {
                  messages: [
                    {
                      id: 1,
                      role: "user",
                      content: "Generate the selected artifact",
                      action_plan_id: 9,
                    },
                    {
                      id: 2,
                      role: "assistant",
                      content: currentPlan.explanation,
                      action_plan_id: 9,
                    },
                  ],
                  plans: [currentPlan],
                }
              : { messages: [], plans: [] },
          ),
        );
      }
      if (path === "/api/transformations/4/chat" && init?.method === "POST") {
        hasPlan = true;
        return Promise.resolve(response(plan, 201));
      }
      if (path === "/api/action-plans/9/confirm") {
        isConfirmed = true;
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({
          plan_hash: "a".repeat(64),
          plan_version: 1,
        });
        return Promise.resolve(response({ ...plan, status: "completed" }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionPlanChat transformationId={4} />);
    fireEvent.change(
      await screen.findByLabelText("Describe what you want to do"),
      {
        target: { value: "Generate the selected artifact" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Propose action" }));

    expect(
      await screen.findByText("Generate the executive summary"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm plan" }),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/action-plans/9/confirm",
      expect.anything(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm plan" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/action-plans/9/confirm",
        expect.anything(),
      ),
    );
    expect(await screen.findByText("completed")).toBeInTheDocument();
  });

  it("keeps read-only clarification plans free of confirmation controls", async () => {
    const clarification = { ...plan, steps: [], requires_confirmation: false };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/transformations/4/chat" && !init?.method) {
        return Promise.resolve(
          response({
            messages: [
              {
                id: 1,
                role: "assistant",
                content: "Which artifact should I use?",
                action_plan_id: 9,
              },
            ],
            plans: [clarification],
          }),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionPlanChat transformationId={4} />);
    expect(
      await screen.findByText("Which artifact should I use?"),
    ).toBeInTheDocument();
    expect(screen.getByText(/No mutation was proposed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("rejects the exact proposed plan and shows its final state", async () => {
    let currentPlan = plan;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/transformations/4/chat" && !init?.method) {
        return Promise.resolve(
          response({
            messages: [
              {
                id: 2,
                role: "assistant",
                content: currentPlan.explanation,
                action_plan_id: 9,
              },
            ],
            plans: [currentPlan],
          }),
        );
      }
      if (path === "/api/action-plans/9/reject") {
        expect(JSON.parse(String(init?.body))).toEqual({
          plan_hash: "a".repeat(64),
          plan_version: 1,
        });
        currentPlan = { ...plan, status: "rejected" };
        return Promise.resolve(response(currentPlan));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionPlanChat transformationId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("rejected")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/action-plans/9/reject",
      expect.anything(),
    );
    expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
  });

  it("shows failed and skipped steps and reports a stale plan", async () => {
    let currentPlan = plan;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/transformations/4/chat" && !init?.method) {
        return Promise.resolve(
          response({
            messages: [
              {
                id: 2,
                role: "assistant",
                content: currentPlan.explanation,
                action_plan_id: 9,
              },
            ],
            plans: [currentPlan],
          }),
        );
      }
      if (path === "/api/action-plans/9/confirm") {
        currentPlan = { ...plan, status: "expired" };
        return Promise.resolve(
          response({ error: { code: "plan_stale" } }, 409),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionPlanChat transformationId={4} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm plan" }),
    );

    expect(
      await screen.findByText(
        "The workspace changed. Review the latest state and create a new plan.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
  });

  it("renders partial execution progress and a safe failed-step result", async () => {
    const partial = {
      ...plan,
      status: "partially_completed",
      steps: [
        { ...plan.steps[0], status: "completed", result_reference: "job 24" },
        {
          ...plan.steps[0],
          id: 12,
          ordinal: 2,
          summary: "Retry the advisory",
          status: "failed",
          error_code: "provider_failed",
        },
        {
          ...plan.steps[0],
          id: 13,
          ordinal: 3,
          summary: "Review the resulting version",
          status: "skipped",
        },
      ],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/api/transformations/4/chat") {
        return Promise.resolve(
          response({
            messages: [
              {
                id: 2,
                role: "assistant",
                content: "The plan stopped after a failed step.",
                action_plan_id: 9,
              },
            ],
            plans: [partial],
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionPlanChat transformationId={4} />);

    expect(await screen.findByText("partially completed")).toBeInTheDocument();
    expect(screen.getByText("Result: job 24")).toBeInTheDocument();
    expect(
      screen.getByText("Could not complete: provider_failed"),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "skipped" })).toBeInTheDocument();
  });
});
