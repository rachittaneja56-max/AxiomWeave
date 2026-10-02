import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as pptxExport from "./pptx";

const preparedRequest = {
  source_text: "The team will open a community garden on Saturday.",
  output_types: ["executive_summary", "linkedin_post", "presentation"],
  audience: "Local residents",
  tone: "Welcoming",
  language: "English",
  detail_level: "standard",
  objective: "Announce the opening",
  style: "Plain language",
  supporting_context: "",
};

const savedResponse = {
  status: "saved",
  transformation_run_id: 10,
  source_id: 20,
  source_version: {
    id: 30,
    version_number: 1,
    content_hash: "a".repeat(64),
    segment_count: 2,
  },
  output_types: ["executive_summary", "linkedin_post", "presentation"],
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function installWorkspaceFetch(fetchMock: ReturnType<typeof vi.fn>) {
  const delegateFetch = fetchMock as unknown as (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<unknown>;
  const routedFetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (input === "/api/auth/session") {
      return Promise.resolve(
        jsonResponse({ authenticated: true, username: "judge_demo" }),
      );
    }
    if (input === "/api/transformations" && init?.method !== "POST") {
      return Promise.resolve(jsonResponse([]));
    }
    return delegateFetch(input, init);
  });
  vi.stubGlobal("fetch", routedFetch);
}

async function renderAuthenticatedWorkspace() {
  render(<App />);
  await screen.findByRole("heading", { name: "Transformations" });
  fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
  expect(
    screen.getByRole("button", { name: "Close navigation menu" }),
  ).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "New transformation" }),
  );
  expect(
    screen.getByRole("button", { name: "Open navigation menu" }),
  ).toHaveAttribute("aria-expanded", "false");
  await screen.findByRole("heading", { name: "New transformation" });
}

function fillRequiredControls() {
  fireEvent.change(screen.getByLabelText("Text source"), {
    target: { value: preparedRequest.source_text },
  });
  fireEvent.change(screen.getByLabelText("Audience"), {
    target: { value: preparedRequest.audience },
  });
  fireEvent.change(screen.getByLabelText("Tone"), {
    target: { value: preparedRequest.tone },
  });
  fireEvent.change(screen.getByLabelText("Objective"), {
    target: { value: preparedRequest.objective },
  });
  fireEvent.change(screen.getByLabelText("Style"), {
    target: { value: preparedRequest.style },
  });
}

function selectMultipleOutputs() {
  for (const output of [
    "Executive Summary",
    "Professional Post",
    "Presentation",
  ]) {
    fireEvent.click(screen.getByRole("checkbox", { name: output }));
  }
}

function reviewArtifact(
  artifactRunId: number,
  outputType: string,
  status: "pending" | "succeeded" | "failed",
  content?: string,
) {
  return {
    artifact_run_id: artifactRunId,
    output_type: outputType,
    status,
    versions: content
      ? [
          {
            id: artifactRunId + 10,
            version_number: 1,
            source_version_id: 30,
            source_version_number: 1,
            content,
            provider: "openai",
            model: "gpt-6-luna",
            prompt_version: "1",
            prompt_hash: "b".repeat(64),
            review_status: "draft",
            created_at: "2026-10-02T00:00:00Z",
          },
        ]
      : [],
  };
}

function reviewDetail(
  status: "Generating" | "Review Required" | "Partial Failure",
  artifactRuns: ReturnType<typeof reviewArtifact>[],
) {
  return {
    transformation_run_id: 10,
    source_version: savedResponse.source_version,
    controls: {
      audience: preparedRequest.audience,
      tone: preparedRequest.tone,
      language: preparedRequest.language,
      detail_level: preparedRequest.detail_level,
      objective: preparedRequest.objective,
      style: preparedRequest.style,
    },
    output_types: artifactRuns.map((artifact) => artifact.output_type),
    status,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    artifact_runs: artifactRuns,
  };
}

describe("transformation request form", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("renders the request controls and permits selecting multiple outputs", async () => {
    installWorkspaceFetch(vi.fn());

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByText("Supporting context", { exact: true }));

    expect(
      screen.getByRole("heading", { name: "New transformation" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Text source")).toBeInTheDocument();
    expect(screen.getByLabelText("Additional guidance")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Context can guide the writing, but it is not treated as source evidence.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(5);
    expect(
      screen.getByRole("checkbox", { name: "X Post" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Infographic|Video package/i),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Paste text" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("tab", { name: "Upload a file" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Import from URL" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Audience")).toBeInTheDocument();
    expect(screen.getByLabelText("Tone")).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toHaveValue("English");
    expect(screen.getByLabelText("Detail")).toHaveValue("standard");
    expect(screen.getByLabelText("Objective")).toBeInTheDocument();
    expect(screen.getByLabelText("Style")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Executive Summary" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Professional Post" }),
    );

    expect(
      screen.getByRole("checkbox", { name: "Executive Summary" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Professional Post" }),
    ).toBeChecked();
  });

  it("opens a saved artifact history and records an acceptance decision", async () => {
    let reviewStatus: "draft" | "accepted" = "draft";
    let sourceRevisionCreated = false;
    let failEvidenceAnalysisOnce = true;
    const artifactVersion = () => ({
      id: 101,
      artifact_run_id: 41,
      version_number: 1,
      source_version_id: 30,
      source_version_number: 1,
      content: JSON.stringify({
        title: "Garden Update",
        slides: [
          {
            title: "Opening",
            key_message: "The garden opens Saturday.",
            bullets: ["Meet at the north gate."],
            visual_recommendation: "A simple garden map.",
            speaker_notes: "Welcome the neighbors.",
          },
          {
            title: "Visit",
            key_message: "Visitors enter at the north gate.",
            bullets: ["Use the north gate."],
            visual_recommendation: "Mark the north gate on a map.",
            speaker_notes: "Point out the entrance.",
          },
        ],
      }),
      provider: "openai",
      model: "gpt-6-luna",
      prompt_version: "presentation_v1",
      prompt_hash: "b".repeat(64),
      review_status: reviewStatus,
      created_at: "2026-09-29T00:00:00Z",
    });
    const detail = () => ({
      transformation_run_id: 10,
      source_version: {
        id: sourceRevisionCreated ? 31 : 30,
        version_number: sourceRevisionCreated ? 2 : 1,
        content_hash: sourceRevisionCreated ? "c".repeat(64) : "a".repeat(64),
        created_at: "2026-09-29T00:00:00Z",
      },
      controls: { audience: "Local residents" },
      output_types: ["presentation"],
      status: "Review Required",
      created_at: "2026-09-29T00:00:00Z",
      updated_at: "2026-09-29T00:00:00Z",
      artifact_runs: [
        {
          artifact_run_id: 41,
          output_type: "presentation",
          status: "succeeded",
          versions: [artifactVersion()],
        },
      ],
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === "/api/auth/session") {
        return Promise.resolve(
          jsonResponse({ authenticated: true, username: "judge_demo" }),
        );
      }
      if (input === "/api/transformations" && init?.method !== "POST") {
        return Promise.resolve(
          jsonResponse([
            {
              transformation_run_id: 10,
              source_version: {
                id: 30,
                version_number: 1,
                content_hash: "a".repeat(64),
                created_at: "2026-09-29T00:00:00Z",
              },
              output_types: ["presentation"],
              artifact_states: [
                {
                  output_type: "presentation",
                  status: "succeeded",
                  latest_version_number: 1,
                  review_status: reviewStatus,
                },
              ],
              status: "Review Required",
              created_at: "2026-09-29T00:00:00Z",
              updated_at: "2026-09-29T00:00:00Z",
            },
          ]),
        );
      }
      if (input === "/api/transformations/10") {
        return Promise.resolve(jsonResponse(detail()));
      }
      if (input === "/api/transformations/10/revision-impact") {
        return Promise.resolve(
          jsonResponse({
            transformation_run_id: 10,
            parent_source_version: sourceRevisionCreated
              ? {
                  id: 30,
                  version_number: 1,
                  content_hash: "a".repeat(64),
                  created_at: "2026-09-29T00:00:00Z",
                }
              : null,
            source_version: {
              id: sourceRevisionCreated ? 31 : 30,
              version_number: sourceRevisionCreated ? 2 : 1,
              content_hash: sourceRevisionCreated
                ? "c".repeat(64)
                : "a".repeat(64),
              created_at: "2026-09-29T00:00:00Z",
            },
            changes: sourceRevisionCreated
              ? [
                  {
                    change_type: "changed",
                    locator: "paragraph:1",
                    old_text: "The center opened on Saturday.",
                    new_text: "The center opened on Sunday.",
                  },
                ]
              : [],
            potentially_affected_artifacts: sourceRevisionCreated
              ? [
                  {
                    artifact_run_id: 41,
                    artifact_version_id: 101,
                    output_type: "presentation",
                    artifact_version_number: 1,
                    evidence_claims: ["The center opened on Saturday."],
                  },
                ]
              : [],
          }),
        );
      }
      if (
        input === "/api/transformations/10/source-versions" &&
        init?.method === "POST"
      ) {
        sourceRevisionCreated = true;
        return Promise.resolve(
          jsonResponse({
            transformation_run_id: 10,
            parent_source_version: {
              id: 30,
              version_number: 1,
              content_hash: "a".repeat(64),
              created_at: "2026-09-29T00:00:00Z",
            },
            source_version: {
              id: 31,
              version_number: 2,
              content_hash: "c".repeat(64),
              created_at: "2026-09-29T00:00:00Z",
            },
            changes: [],
            potentially_affected_artifacts: [],
          }),
        );
      }
      if (
        input === "/api/artifact-versions/101/evidence/analyze" &&
        init?.method === "POST"
      ) {
        if (failEvidenceAnalysisOnce) {
          failEvidenceAnalysisOnce = false;
          return Promise.resolve(jsonResponse({}, 502));
        }
        return Promise.resolve(
          jsonResponse([
            {
              id: 201,
              artifact_version_id: 101,
              claim_text: "The center opened on Saturday.",
              source_version_id: 30,
              source_segment_id: 301,
              source_quote: "The center opened on Saturday.",
              source_locator: "paragraph:1",
              status: "linked",
              created_at: "2026-09-29T00:00:00Z",
            },
          ]),
        );
      }
      if (input === "/api/source-versions/30") {
        return Promise.resolve(
          jsonResponse({
            id: 30,
            version_number: 1,
            content_hash: "a".repeat(64),
            source_text: "The center opened on Saturday.",
          }),
        );
      }
      if (
        input === "/api/artifact-runs/41/targeted-update" &&
        init?.method === "POST"
      ) {
        return Promise.resolve(jsonResponse({ status: "succeeded" }));
      }
      if (
        input === "/api/artifact-runs/41/regenerate" &&
        init?.method === "POST"
      ) {
        return Promise.resolve(jsonResponse({ status: "succeeded" }));
      }
      if (
        input === "/api/artifact-versions/101/review" &&
        init?.method === "PATCH"
      ) {
        reviewStatus = "accepted";
        return Promise.resolve(jsonResponse(artifactVersion()));
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Transformations" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: "The center opened on Saturday.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("AxiomWeave")).toBeInTheDocument();
    expect(screen.getByText("judge_demo")).toBeInTheDocument();
    expect(document.body.textContent).toMatch(
      /Source V1\s*·\s*Updated[\s\S]*?·\s*1 artifact/,
    );
    expect(document.body.textContent).not.toContain("\uFFFD");
    expect(
      screen.queryByText(/SIH|NTRO|SHA-256|Backend connected/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Artifacts ready to review"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Not selected")).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "The center opened on Saturday.",
      }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "The center opened on Saturday.",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Source V1" }));
    expect(
      await screen.findByRole("dialog", { name: "Source V1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The center opened on Saturday.", {
        selector: ".source-viewer__body",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("a".repeat(64))).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Source V1" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View source" }));
    expect(
      await screen.findByRole("dialog", { name: "Source V1" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Close source viewer" }),
    );
    expect(screen.getByText("The garden opens Saturday.")).toBeInTheDocument();
    expect(screen.queryByText("openai")).not.toBeInTheDocument();
    expect(screen.queryByText("gpt-6-luna")).not.toBeInTheDocument();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal(
      "navigator",
      Object.assign(Object.create(navigator), {
        clipboard: { writeText },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy artifact" }));
    expect(
      await screen.findByText("Artifact copied to clipboard."),
    ).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("The garden opens Saturday."),
    );
    const downloadedBlobs: Blob[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", {
      createObjectURL: (blob: Blob) => {
        downloadedBlobs.push(blob);
        return "blob:artifact-export";
      },
      revokeObjectURL: vi.fn(),
    });
    const renderPptx = vi
      .spyOn(pptxExport, "renderPresentationPptx")
      .mockResolvedValue(new Blob(["pptx"], { type: "application/zip" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Download PowerPoint" }),
    );
    expect(
      await screen.findByText("Editable PowerPoint downloaded."),
    ).toBeInTheDocument();
    expect(renderPptx).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByLabelText("More artifact actions"));
    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));
    expect(
      await screen.findByText("Presentation Markdown downloaded."),
    ).toBeInTheDocument();
    const markdown = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(downloadedBlobs[1]);
    });
    expect(markdown).toContain("# Slide 1 — Opening");
    expect(markdown).toContain("**Key message**");
    expect(markdown).toContain("**Visual recommendation**");
    expect(markdown).toContain("**Speaker notes**");
    expect(markdown).toContain("Welcome the neighbors.");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Opening");
    expect(document.querySelector(".slide-canvas--16x9")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Slide 2/ }));
    expect(screen.getByLabelText("Title")).toHaveValue("Visit");
    fireEvent.change(screen.getByLabelText("Key message"), {
      target: { value: "New live preview" },
    });
    expect(
      screen.getByText("New live preview", {
        selector: ".slide-canvas__message",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      await screen.findByText("The garden opens Saturday."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "Traceability" })[0]);
    expect(
      screen.getByRole("dialog", { name: "Traceability" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Traceability" }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Traceability" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Traceability" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Close traceability" }));
    expect(
      screen.queryByRole("dialog", { name: "Traceability" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Traceability" })[0]);
    fireEvent.click(screen.getByRole("tab", { name: "Versions" }));
    expect(await screen.findByText(/Source V1.*Accepted/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/artifact-versions/101/review",
      expect.objectContaining({ method: "PATCH", credentials: "include" }),
    );

    fireEvent.click(screen.getByRole("tab", { name: "Details" }));
    const provenance = screen.getByText("Technical provenance");
    expect(provenance.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(provenance);
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("gpt-6-luna")).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Analyze claims" }));
    expect(
      await screen.findByText("Claims could not be analyzed. Please retry."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Analyze claims" }));
    expect(
      await screen.findByText("The center opened on Saturday.", {
        selector: "blockquote",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View in source" }));
    expect(
      await screen.findByRole("dialog", { name: "Source V1" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("The center opened on Saturday.", {
        selector: "mark",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Close source viewer" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Update source" }));
    expect(await screen.findByLabelText("Source text")).toHaveValue(
      "The center opened on Saturday.",
    );
    fireEvent.change(screen.getByLabelText("Source text"), {
      target: { value: "The center opened on Sunday." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "View changes" }),
    );
    expect(await screen.findByText("1 change from V1")).toBeInTheDocument();
    expect(
      screen.getByText("The center opened on Sunday.", { selector: "ins" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Targeted update" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/artifact-runs/41/targeted-update",
        expect.objectContaining({ method: "POST", credentials: "include" }),
      ),
    );
    expect(
      screen.getByRole("button", { name: "Full regeneration" }),
    ).toBeInTheDocument();
  }, 10000);

  it("navigates artifacts, checks sibling warnings, and renders Markdown safely", async () => {
    const sourceVersion = {
      id: 30,
      version_number: 1,
      content_hash: "a".repeat(64),
      created_at: "2026-09-29T00:00:00Z",
    };
    const summaryVersion = {
      id: 51,
      artifact_run_id: 50,
      version_number: 1,
      source_version_id: 30,
      source_version_number: 1,
      content:
        "## Update\n\nThe center opens Saturday.\n\n<script>alert('x')</script>",
      provider: "openai",
      model: "gpt-6-luna",
      prompt_version: "summary_v1",
      prompt_hash: "c".repeat(64),
      review_status: "draft",
      created_at: "2026-09-29T00:00:00Z",
    };
    const presentationVersion = {
      ...summaryVersion,
      id: 52,
      artifact_run_id: 53,
      content: JSON.stringify({
        title: "Next steps",
        slides: [
          {
            title: "Opening",
            key_message: "The center opens Sunday.",
            bullets: ["Doors open at 9 am."],
            visual_recommendation: "A calendar card.",
            speaker_notes: "Explain the updated schedule.",
          },
        ],
      }),
    };
    const detail = {
      transformation_run_id: 10,
      source_version: sourceVersion,
      controls: { audience: "Residents" },
      output_types: ["executive_summary", "presentation", "advisory"],
      status: "Review Required",
      created_at: "2026-09-29T00:00:00Z",
      updated_at: "2026-09-29T00:00:00Z",
      artifact_runs: [
        {
          artifact_run_id: 50,
          output_type: "executive_summary",
          status: "succeeded",
          versions: [summaryVersion],
        },
        {
          artifact_run_id: 53,
          output_type: "presentation",
          status: "succeeded",
          versions: [presentationVersion],
        },
        {
          artifact_run_id: 54,
          output_type: "advisory",
          status: "succeeded",
          versions: [
            {
              ...presentationVersion,
              id: 53,
              artifact_run_id: 54,
              content: "The center opens at noon.",
            },
          ],
        },
      ],
    };
    const finding = {
      id: 201,
      source_version_id: 30,
      artifact_version_a_id: 51,
      artifact_version_b_id: 52,
      statement_a: "The center opens Saturday.",
      statement_b: "The center opens Sunday.",
      discrepancy_type: "schedule_difference",
      explanation: "The drafts give different opening days.",
      review_status: "open",
      created_at: "2026-09-29T00:00:00Z",
    };
    let failAllComparisons = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === "/api/auth/session") {
        return Promise.resolve(
          jsonResponse({ authenticated: true, username: "judge_demo" }),
        );
      }
      if (input === "/api/transformations") {
        return Promise.resolve(
          jsonResponse([
            {
              transformation_run_id: 10,
              source_version: sourceVersion,
              output_types: ["executive_summary", "presentation"],
              artifact_states: [],
              status: "Review Required",
              created_at: "2026-09-29T00:00:00Z",
              updated_at: "2026-09-29T00:00:00Z",
            },
          ]),
        );
      }
      if (input === "/api/source-versions/30") {
        return Promise.resolve(
          jsonResponse({
            ...sourceVersion,
            source_text:
              "# Community center updates\n\nThe community center opens Saturday.",
          }),
        );
      }
      if (input === "/api/transformations/10") {
        return Promise.resolve(jsonResponse(detail));
      }
      if (input === "/api/transformations/10/revision-impact") {
        return Promise.resolve(
          jsonResponse({
            transformation_run_id: 10,
            parent_source_version: null,
            source_version: sourceVersion,
            changes: [],
            potentially_affected_artifacts: [],
          }),
        );
      }
      if (input === "/api/discrepancies/analyze") {
        const callNumber = fetchMock.mock.calls.filter(
          ([path]) => path === "/api/discrepancies/analyze",
        ).length;
        if (callNumber === 1 || failAllComparisons)
          return Promise.resolve(jsonResponse({}, 502));
        if (callNumber === 3)
          return Promise.resolve(jsonResponse({ finding: null }));
        const pair = JSON.parse(String(init?.body)) as {
          artifact_version_a_id: number;
          artifact_version_b_id: number;
        };
        return Promise.resolve(
          jsonResponse({
            finding: {
              ...finding,
              id: callNumber === 2 ? 202 : 201,
              artifact_version_a_id: pair.artifact_version_a_id,
              artifact_version_b_id: pair.artifact_version_b_id,
              explanation:
                callNumber === 2
                  ? "The drafts give different opening days."
                  : "The opening dates also differ.",
            },
          }),
        );
      }
      if (
        input === "/api/artifact-versions/51/review" &&
        init?.method === "PATCH"
      ) {
        const reviewStatus = JSON.parse(String(init.body)).review_status;
        summaryVersion.review_status = reviewStatus;
        return Promise.resolve(jsonResponse(summaryVersion));
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByRole("button", { name: "Community center updates" });
    fireEvent.click(
      await screen.findByRole("button", { name: "Community center updates" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Executive Summary" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Review navigation" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Artifacts" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Source V1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Executive Summary" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.queryByRole("button", { name: "X Post" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Formal Advisory" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Update" })).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(
      screen.queryByText(/SIH|NTRO|Backend connected|SHA-256/i),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("More artifact actions"));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/artifact-versions/51/review",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ review_status: "rejected" }),
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Presentation" }));
    expect(
      await screen.findByRole("heading", { name: "Presentation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Opening" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Traceability" })[0]);
    fireEvent.click(screen.getByRole("tab", { name: "Warnings" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Check sibling consistency" }),
    );
    expect(
      await screen.findByText("The drafts give different opening days."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Some sibling comparisons could not be completed/),
    ).toBeInTheDocument();
    expect(screen.getByText("Possible discrepancy")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/discrepancies/analyze",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(
      fetchMock.mock.calls.filter(
        ([path]) => path === "/api/discrepancies/analyze",
      ),
    ).toHaveLength(3);
    fireEvent.click(
      screen.getByRole("button", { name: "Check sibling consistency" }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([path]) => path === "/api/discrepancies/analyze",
        ),
      ).toHaveLength(4),
    );
    expect(
      screen.queryByText(/Some sibling comparisons could not be completed/),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText("The opening dates also differ."),
    ).toBeInTheDocument();
    failAllComparisons = true;
    fireEvent.click(
      screen.getByRole("button", { name: "Check sibling consistency" }),
    );
    expect(
      await screen.findByText(
        "Sibling consistency could not be checked. Please retry.",
      ),
    ).toBeInTheDocument();
  });

  it("extracts a selected file and submits its canonical source text", async () => {
    const extractedSource = "A fictional report about a community garden.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          filename: "garden.md",
          media_type: "text/markdown",
          character_count: extractedSource.length,
          source_text: extractedSource,
          ocr_used: true,
          source_id: 76,
          source_version_id: 77,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(savedResponse))
      .mockResolvedValueOnce(
        jsonResponse({ status: "succeeded", artifacts: [] }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: "Upload a file" }));
    const file = new File([extractedSource], "garden.md", {
      type: "text/markdown",
    });
    fireEvent.change(screen.getByLabelText("Upload source file"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("status")
          .some((status) => status.textContent?.includes("garden.md")),
      ).toBe(true),
    );
    expect(
      screen
        .getAllByRole("status")
        .find((status) => status.textContent?.includes("garden.md"))
        ?.textContent,
    ).toContain("44 characters");
    expect(screen.getByText("OCR used on scanned pages")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/sources/file",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );

    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));
    await screen.findByRole("heading", { name: "Generation results" });
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string).source_text,
    ).toBe(extractedSource);
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string),
    ).toHaveProperty("supporting_context", "");
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string),
    ).toHaveProperty("source_version_id", 77);
  });

  it("imports one public URL and uses its extracted text as the source", async () => {
    const extractedSource = "An article about a public garden opening.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          source_url: "https://example.test/article",
          final_url: "https://example.test/article",
          title: "Garden article",
          character_count: extractedSource.length,
          source_text: extractedSource,
          extraction_method: "url_html",
          source_id: 88,
          source_version_id: 89,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(savedResponse))
      .mockResolvedValueOnce(
        jsonResponse({ status: "succeeded", artifacts: [] }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: "Import from URL" }));
    fireEvent.change(screen.getByLabelText("Public page URL"), {
      target: { value: "https://example.test/article" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Read public page" }));
    expect(
      await screen.findByText("Imported page: Garden article"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/sources/url",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ url: "https://example.test/article" }),
      }),
    );
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));
    await screen.findByRole("heading", { name: "Generation results" });
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string).source_text,
    ).toBe(extractedSource);
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string),
    ).toHaveProperty("source_version_id", 89);
  });

  it("shows extraction errors and rejects malformed successful responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "invalid_encoding",
              message: "The file must contain valid UTF-8 text.",
            },
          },
          422,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ filename: "bad.txt", source_text: "missing metadata" }),
      );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: "Upload a file" }));
    const file = new File(["plain text"], "source.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Upload source file"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("valid UTF-8");

    fireEvent.change(screen.getByLabelText("Upload source file"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "expected format",
    );
  });

  it("shows a safe message when file extraction cannot reach the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("private network detail"));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: "Upload a file" }));
    const file = new File(["plain text"], "source.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Upload source file"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the service",
    );
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });

  it("clears uploaded content when switching source modes", async () => {
    const extractedSource = "Uploaded source content";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          filename: "source.txt",
          media_type: "text/plain",
          character_count: extractedSource.length,
          source_text: extractedSource,
          ocr_used: false,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(savedResponse));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: "Upload a file" }));
    const file = new File([extractedSource], "source.txt", {
      type: "text/plain",
    });
    fireEvent.change(screen.getByLabelText("Upload source file"), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("status")
          .some((status) => status.textContent?.includes("source.txt")),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    expect(screen.getByLabelText("Text source")).toHaveValue("");

    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Add source text",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits the canonical multi-output request and shows the ready state", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(savedResponse))
      .mockResolvedValueOnce(
        jsonResponse({
          status: "running",
          artifacts: [
            {
              artifact_run_id: 40,
              output_type: "executive_summary",
              status: "pending",
              artifact_version: null,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          reviewDetail("Review Required", [
            reviewArtifact(
              40,
              "executive_summary",
              "succeeded",
              "A short generated summary.",
            ),
          ]),
        ),
      )
      .mockResolvedValueOnce(jsonResponse({}));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    fireEvent.click(screen.getByText("Supporting context", { exact: true }));
    fireEvent.change(screen.getByLabelText("Additional guidance"), {
      target: { value: "For local administrators." },
    });
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));

    expect(
      await screen.findByText("A short generated summary."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Generation results" }),
    ).toBeNull();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/transformations/10/generate",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transformations/10",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/transformations",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...preparedRequest,
          supporting_context: "For local administrators.",
        }),
      }),
    );
  });

  it("shows independent output results and retries only the failed artifact", async () => {
    const presentationContent = JSON.stringify({
      title: "Community center",
      slides: [
        {
          title: "Opening",
          key_message: "The center opened Saturday.",
          bullets: ["Opening day was Saturday."],
          visual_recommendation: "Entrance photo.",
          speaker_notes: "Welcome the community.",
        },
        {
          title: "Next steps",
          key_message: "Visit during posted hours.",
          bullets: ["Check the posted schedule."],
          visual_recommendation: "Hours sign.",
          speaker_notes: "Share the schedule.",
        },
      ],
    });
    const successfulVersion = {
      id: 50,
      version_number: 1,
      source_version_id: 30,
      source_version_number: 1,
      content: "A short generated summary.",
      provider: "openai",
      model: "gpt-6-luna",
      prompt_version: "1",
      prompt_hash: "b".repeat(64),
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          ...savedResponse,
          output_types: ["executive_summary", "advisory", "presentation"],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "partial_failure",
          artifacts: [
            {
              artifact_run_id: 40,
              output_type: "executive_summary",
              status: "pending",
              artifact_version: null,
            },
            {
              artifact_run_id: 41,
              output_type: "advisory",
              status: "pending",
              artifact_version: null,
            },
            {
              artifact_run_id: 42,
              output_type: "presentation",
              status: "pending",
              artifact_version: null,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ...reviewDetail("Partial Failure", [
            reviewArtifact(
              40,
              "executive_summary",
              "succeeded",
              successfulVersion.content,
            ),
            reviewArtifact(41, "advisory", "failed"),
            reviewArtifact(
              42,
              "presentation",
              "succeeded",
              presentationContent,
            ),
          ]),
        }),
      )
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(
        jsonResponse({
          artifact_run_id: 41,
          output_type: "advisory",
          status: "pending",
          artifact_version: null,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          reviewDetail("Generating", [
            reviewArtifact(
              40,
              "executive_summary",
              "succeeded",
              successfulVersion.content,
            ),
            reviewArtifact(41, "advisory", "pending"),
            reviewArtifact(
              42,
              "presentation",
              "succeeded",
              presentationContent,
            ),
          ]),
        ),
      )
      .mockResolvedValueOnce(jsonResponse({}));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    for (const output of [
      "Executive Summary",
      "Formal Advisory",
      "Presentation",
    ]) {
      fireEvent.click(screen.getByRole("checkbox", { name: output }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));

    expect(await screen.findByText("Needs attention")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Executive Summary" }));
    expect(
      await screen.findByText("A short generated summary."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Formal Advisory" }));
    expect(screen.getByText(/No version yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry artifact" }));
    expect(await screen.findByText(/No version yet/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/artifact-runs/41/retry",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/artifact-runs/40/regenerate",
      expect.anything(),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/artifact-runs/42/regenerate",
      expect.anything(),
    );
  });

  it("gives local feedback for missing source and output selection", async () => {
    const fetchMock = vi.fn();
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Add source text",
    );
    expect(fetchMock).toHaveBeenCalledTimes(0);

    fireEvent.change(screen.getByLabelText("Text source"), {
      target: { value: "A fictional team announcement." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose at least one artifact",
    );
    expect(fetchMock).toHaveBeenCalledTimes(0);
  });

  it("shows safe field feedback for backend validation failures", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "invalid_request",
            message: "Request is invalid",
            fields: [{ field: "audience", message: "Value is too long" }],
          },
        },
        422,
      ),
    );
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Please review: Audience",
    );
    expect(screen.queryByText("Value is too long")).not.toBeInTheDocument();
  });

  it("handles a network failure without displaying backend details", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("private network detail"));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your source could not be saved",
    );
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });

  it("rejects an unexpected successful response shape", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "saved" }));
    installWorkspaceFetch(fetchMock);

    await renderAuthenticatedWorkspace();
    fillRequiredControls();
    selectMultipleOutputs();
    fireEvent.click(screen.getByRole("button", { name: "Generate artifacts" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected save response",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps the authenticated workspace visible when logout fails", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("private detail"));
    installWorkspaceFetch(fetchMock);
    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign out could not be completed",
    );
    expect(screen.getByLabelText("Text source")).toBeInTheDocument();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
  });

  it("keeps the workspace visible when logout returns a failure status", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({}, 503));
    installWorkspaceFetch(fetchMock);
    await renderAuthenticatedWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign out could not be completed",
    );
    expect(screen.getByLabelText("Text source")).toBeInTheDocument();
  });
});

describe("AxiomWeave sign-in", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("keeps the workspace hidden while session state is unresolved", () => {
    let resolveSession:
      ((response: ReturnType<typeof jsonResponse>) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolveSession = resolve;
          }),
      ),
    );
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your AxiomWeave workspace",
    );
    expect(screen.queryByLabelText("Text source")).not.toBeInTheDocument();
    resolveSession?.(jsonResponse({}, 401));
  });

  it("shows username and password login without social sign-in", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((url: string) =>
          Promise.resolve(
            url === "/api/auth/config"
              ? jsonResponse({ registration_enabled: false })
              : jsonResponse({}, 401),
          ),
        ),
    );
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Welcome back" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(
      screen.queryByRole("button", { name: /google/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/forgot password/i)).not.toBeInTheDocument();
  });

  it("sends username/password and opens the workspace on success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ registration_enabled: false }))
      .mockResolvedValueOnce(
        jsonResponse({ authenticated: true, username: "judge_demo" }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByRole("heading", { name: "Welcome back" });
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "judge_demo" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "fictional test passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Transformations" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          username: "judge_demo",
          password: "fictional test passphrase",
        }),
      }),
    );
  });

  it("uses a generic login failure and never displays the password", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ registration_enabled: false }))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "invalid_credentials",
              message: "Invalid username or password.",
            },
          },
          401,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByLabelText("Username");
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "nobody" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "private fictional phrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid username or password.",
    );
    expect(
      screen.queryByText("private fictional phrase"),
    ).not.toBeInTheDocument();
  });

  it("shows registration only when enabled and submits new credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ registration_enabled: true }))
      .mockResolvedValueOnce(
        jsonResponse({ authenticated: true, username: "judge_demo" }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Need an account? Create one",
      }),
    );
    expect(
      screen.getByText(
        "Use at least 15 characters. Passphrases and spaces are allowed.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "autocomplete",
      "new-password",
    );
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "judge_demo" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "fictional test passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Transformations" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/register",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows the throttle response safely", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ registration_enabled: false }))
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "too_many_login_attempts" } }, 429),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByLabelText("Username");
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "judge_demo" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "fictional test passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many sign-in attempts",
    );
  });
});
