import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WeaveAssistant } from "./components/WeaveAssistant";

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

const workspacePlan = {
  id: 9,
  transformation_run_id: 4,
  explanation: "I’ll prepare a new version for review.",
  plan_hash: "a".repeat(64),
  plan_version: 1,
  requires_confirmation: true,
  status: "awaiting_confirmation",
  steps: [
    {
      id: 11,
      ordinal: 1,
      command_type: "regenerate_artifact",
      arguments: { artifact_run_id: 40 },
      summary: "Regenerate Executive Summary",
      consequential: true,
      status: "waiting",
      error_code: null,
      result_reference: null,
    },
  ],
};

describe("global Weave assistant", () => {
  it("opens, follows context changes, and waits for explicit confirmation", async () => {
    let proposed = false;
    let confirmed = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/transformations/4/chat" && init?.method === "POST") {
        proposed = true;
        return Promise.resolve(response(workspacePlan, 201));
      }
      if (path === "/api/transformations/4/chat") {
        const plan = confirmed
          ? {
              ...workspacePlan,
              status: "completed",
              steps: workspacePlan.steps.map((step) => ({
                ...step,
                status: "completed",
              })),
            }
          : workspacePlan;
        return Promise.resolve(
          response(
            proposed
              ? {
                  messages: [
                    {
                      id: 1,
                      role: "user",
                      content: "Regenerate the summary",
                      action_plan_id: null,
                    },
                    {
                      id: 2,
                      role: "assistant",
                      content: "I’ll prepare a new version for review.",
                      action_plan_id: 9,
                    },
                  ],
                  plans: [plan],
                }
              : { messages: [], plans: [] },
          ),
        );
      }
      if (path === "/api/action-plans/9/confirm") {
        confirmed = true;
        expect(JSON.parse(String(init?.body))).toEqual({
          plan_hash: "a".repeat(64),
          plan_version: 1,
        });
        return Promise.resolve(
          response({
            ...workspacePlan,
            status: "completed",
            steps: workspacePlan.steps.map((step) => ({
              ...step,
              status: "completed",
            })),
          }),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onWorkspaceChanged = vi.fn();

    const view = render(
      <WeaveAssistant
        transformationId={4}
        contextLabel="Executive Summary"
        creationMode={false}
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={onWorkspaceChanged}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Open Weave assistant" }),
    );
    expect(await screen.findByText("Executive Summary")).toBeInTheDocument();
    expect(screen.queryByText("Clear draft")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "More Weave actions" }));
    expect(screen.getByRole("button", { name: "Reset draft" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Minimize Weave assistant" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog", { name: "Weave assistant" })).getByRole(
        "button",
        { name: "Close Weave assistant" },
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "More Weave actions" }));
    view.rerender(
      <WeaveAssistant
        transformationId={4}
        contextLabel="Infographic"
        creationMode={false}
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={onWorkspaceChanged}
      />,
    );
    expect(screen.getByText("Infographic")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Regenerate the summary" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByRole("button", { name: "Confirm" }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/confirm"),
      ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onWorkspaceChanged).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/action-plans/9/confirm",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("proposes creation from a source and opens the new workspace only after confirmation", async () => {
    let proposed = false;
    let confirmed = false;
    const request = {
      source_text: "The city will open a new community center on Saturday.",
      output_types: ["executive_summary", "presentation"],
      audience: "Senior leadership",
      tone: "Professional",
      objective: "Inform leadership",
      style: "Plain language",
    };
    const plan = {
      id: 12,
      transformation_run_id: null,
      explanation: "I prepared the creation details for review.",
      plan_hash: "b".repeat(64),
      plan_version: 1,
      requires_confirmation: true,
      status: "awaiting_confirmation",
      steps: [
        {
          id: 13,
          ordinal: 1,
          command_type: "create_transformation",
          arguments: { request },
          summary: "Create an executive summary and presentation",
          consequential: true,
          status: "waiting",
          error_code: null,
          result_reference: null,
        },
      ],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/weave/chat" && init?.method === "POST") {
        proposed = true;
        expect(JSON.parse(String(init.body))).toEqual({
          message: "Create a summary and presentation.",
          source_text: request.source_text,
        });
        return Promise.resolve(response(plan, 201));
      }
      if (path === "/api/weave/chat") {
        return Promise.resolve(
          response(
            proposed
              ? {
                  messages: [
                    {
                      id: 1,
                      role: "user",
                      content: "Create a summary and presentation.",
                      action_plan_id: null,
                    },
                    {
                      id: 2,
                      role: "assistant",
                      content: "I prepared the creation details for review.",
                      action_plan_id: 12,
                    },
                  ],
                  plans: [
                    confirmed
                      ? {
                          ...plan,
                          status: "completed",
                          steps: [
                            {
                              ...plan.steps[0],
                              status: "completed",
                              result_reference: "transformation_run_id:21",
                            },
                          ],
                        }
                      : plan,
                  ],
                }
              : { messages: [], plans: [] },
          ),
        );
      }
      if (path === "/api/action-plans/12/confirm") {
        confirmed = true;
        return Promise.resolve(
          response({
            ...plan,
            status: "completed",
            steps: [
              {
                ...plan.steps[0],
                status: "completed",
                result_reference: "transformation_run_id:21",
              },
            ],
          }),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onTransformationCreated = vi.fn();

    render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Creating a transformation"
        creationMode
        creationPage
        onExitCreationPage={() => {}}
        onNavigateNew={() => {}}
        onTransformationCreated={onTransformationCreated}
        onWorkspaceChanged={() => {}}
      />,
    );
    expect(
      await screen.findByRole("region", { name: "Weave assistant" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add a source" }));
    fireEvent.change(screen.getByLabelText("Paste your source"), {
      target: { value: request.source_text },
    });
    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Create a summary and presentation." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByText("Outputs: Executive Summary, Presentation"),
    ).toBeInTheDocument();
    expect(onTransformationCreated).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Create transformation" }),
    );
    await waitFor(() =>
      expect(onTransformationCreated).toHaveBeenCalledWith(
        21,
        expect.any(String),
        1,
      ),
    );
  });

  it("closes on Escape and returns focus to the launcher", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response({ messages: [], plans: [] }))),
    );
    render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Dashboard"
        creationMode={false}
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={() => {}}
      />,
    );
    const launcher = screen.getByRole("button", {
      name: "Open Weave assistant",
    });
    fireEvent.click(launcher);
    expect(
      await screen.findByRole("dialog", { name: "Weave assistant" }),
    ).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Weave assistant" }),
    ).toBeNull();
    expect(launcher).toHaveFocus();
  });
});
