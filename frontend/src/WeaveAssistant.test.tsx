import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WeaveAssistant } from "./components/WeaveAssistant";

const styles = readFileSync("src/styles.css", "utf8");

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
    const launcher = document.querySelector(".weave-launcher");
    expect(launcher).toHaveAttribute("aria-expanded", "true");
    expect(launcher).toBeVisible();
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
          command_type: "create_transformation_and_generate",
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
                              result_reference:
                                "transformation_run_id:21;source_version_number:1;generation_status:running",
                              target_ids: {
                                transformation_run_id: 21,
                                source_version_id: 31,
                                source_version_number: 1,
                                artifact_run_executive_summary_id: 41,
                                artifact_run_presentation_id: 42,
                              },
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
                result_reference:
                  "transformation_run_id:21;source_version_number:1;generation_status:running",
                target_ids: {
                  transformation_run_id: 21,
                  source_version_id: 31,
                  source_version_number: 1,
                  artifact_run_executive_summary_id: 41,
                  artifact_run_presentation_id: 42,
                },
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
    fireEvent.click(screen.getByRole("button", { name: "Paste source" }));
    fireEvent.change(screen.getByLabelText("Paste your source"), {
      target: { value: request.source_text },
    });
    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Create a summary and presentation." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByText("Generate: Executive Summary, Presentation"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Source: Pasted source/)).toBeInTheDocument();
    expect(onTransformationCreated).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Create and generate" }),
    );
    await waitFor(() =>
      expect(onTransformationCreated).toHaveBeenCalledWith(
        21,
        expect.any(String),
        1,
        "executive_summary",
        undefined,
      ),
    );
  });

  it("shows an empty-step source clarification without a confirmation card", async () => {
    const emptyPlan = {
      id: 45,
      transformation_run_id: null,
      explanation: "I can create that. Add the source material first.",
      plan_hash: "c".repeat(64),
      plan_version: 1,
      requires_confirmation: false,
      status: "proposed",
      steps: [],
    };
    let proposed = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/weave/chat" && init?.method === "POST") {
        proposed = true;
        expect(JSON.parse(String(init.body))).toEqual({
          message: "Create an infographic.",
        });
        return Promise.resolve(response(emptyPlan, 201));
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
                      content: "Create an infographic.",
                      action_plan_id: null,
                    },
                    {
                      id: 2,
                      role: "assistant",
                      content: emptyPlan.explanation,
                      action_plan_id: 45,
                    },
                  ],
                  plans: [emptyPlan],
                }
              : { messages: [], plans: [] },
          ),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Creating a transformation"
        creationMode
        creationPage
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={() => {}}
      />,
    );
    await screen.findByRole("region", { name: "Weave assistant" });
    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Create an infographic." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText(
        "I can create that. Add the source material first.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Create and generate" }),
    ).toBeNull();
    expect(screen.getByLabelText("Message Weave")).toBeEnabled();
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === "/api/transformations" && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("keeps an attached source and composer active after empty-step clarification", async () => {
    const sourceText = "The city will open a public learning center in June.";
    const emptyPlan = {
      id: 46,
      transformation_run_id: null,
      explanation: "Who is the infographic for?",
      plan_hash: "d".repeat(64),
      plan_version: 1,
      requires_confirmation: false,
      status: "proposed",
      steps: [],
    };
    let proposed = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/weave/chat" && init?.method === "POST") {
        proposed = true;
        expect(JSON.parse(String(init.body))).toEqual({
          message: "Create an infographic.",
          source_text: sourceText,
        });
        return Promise.resolve(response(emptyPlan, 201));
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
                      content: "Create an infographic.",
                      action_plan_id: null,
                    },
                    {
                      id: 2,
                      role: "assistant",
                      content: emptyPlan.explanation,
                      action_plan_id: 46,
                    },
                  ],
                  plans: [emptyPlan],
                }
              : { messages: [], plans: [] },
          ),
        );
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Creating a transformation"
        creationMode
        creationPage
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={() => {}}
      />,
    );
    await screen.findByRole("region", { name: "Weave assistant" });
    fireEvent.click(screen.getByRole("button", { name: "Add a source" }));
    fireEvent.click(screen.getByRole("button", { name: "Paste source" }));
    fireEvent.change(screen.getByLabelText("Paste your source"), {
      target: { value: sourceText },
    });
    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Create an infographic." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText("Who is the infographic for?"),
    ).toBeVisible();
    expect(screen.getByText(/Pasted source · \d+ characters/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.getByLabelText("Message Weave")).toBeEnabled();
  });

  it("removes a failed optimistic message, restores the composer, and keeps refreshed history clean", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/weave/chat" && init?.method === "POST") {
        return Promise.resolve(
          response({ error: { code: "planner_failed" } }, 502),
        );
      }
      if (path === "/api/weave/chat") {
        return Promise.resolve(response({ messages: [], plans: [] }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Creating a transformation"
        creationMode
        creationPage
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={() => {}}
      />,
    );
    await screen.findByRole("region", { name: "Weave assistant" });
    const composer = screen.getByLabelText("Message Weave");
    fireEvent.change(composer, { target: { value: "Create an infographic." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText("Weave couldn't prepare that setup. Try again."),
    ).toBeVisible();
    expect(composer).toHaveValue("Create an infographic.");
    expect(container.querySelector(".weave-message--user")).toBeNull();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input) === "/api/weave/chat" && init?.method !== "POST",
      ),
    ).toHaveLength(2);
  });

  it("submits only once on rapid repeated submit events while Weave is busy", async () => {
    let resolveProposal: ((value: unknown) => void) | undefined;
    let postCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/weave/chat" && init?.method === "POST") {
        postCount += 1;
        return new Promise((resolve) => {
          resolveProposal = () => resolve(response({}));
        });
      }
      if (path === "/api/weave/chat") {
        return Promise.resolve(response({ messages: [], plans: [] }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WeaveAssistant
        transformationId={null}
        contextLabel="Creating a transformation"
        creationMode
        creationPage
        onNavigateNew={() => {}}
        onTransformationCreated={() => {}}
        onWorkspaceChanged={() => {}}
      />,
    );
    await screen.findByRole("region", { name: "Weave assistant" });
    fireEvent.change(screen.getByLabelText("Message Weave"), {
      target: { value: "Create an infographic." },
    });
    const form = screen.getByLabelText("Message Weave").closest("form");
    if (!form) throw new Error("Composer form not found");
    fireEvent.submit(form);
    fireEvent.submit(form);

    expect(postCount).toBe(1);
    expect(screen.getByText("Weave is preparing your setup...")).toBeVisible();
    expect(screen.getAllByText("Create an infographic.")).toHaveLength(1);
    resolveProposal?.(null);
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

  it("docks the contextual panel at bottom-right and keeps its desktop launcher visible", () => {
    expect(styles).toMatch(
      /\.weave-panel\s*\{[^}]*right:\s*24px;[^}]*bottom:\s*82px;/s,
    );
    expect(styles).toMatch(
      /\.weave-panel\s*\{[^}]*height:\s*min\(680px,\s*calc\(100dvh - 120px\)\);/s,
    );
    const expandedLauncherRule = styles.match(
      /\.weave-launcher\[aria-expanded="true"\]\s*\{([^}]*)\}/,
    )?.[1];
    expect(expandedLauncherRule).toContain("background:");
    expect(expandedLauncherRule).not.toContain("visibility: hidden");
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*720px\)[\s\S]*?\.weave-launcher\[aria-expanded="true"\]\s*\{[^}]*visibility:\s*hidden;/,
    );
  });
});
