import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewWorkspace } from "./screens/ReviewWorkspace";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  };
}

function detail(
  status: "Generating" | "Review Required",
  artifactStatus: "pending" | "succeeded",
) {
  return {
    transformation_run_id: 10,
    source_version: {
      id: 30,
      version_number: 1,
      content_hash: "a".repeat(64),
      created_at: "2026-10-02T00:00:00Z",
    },
    controls: {
      audience: "Local residents",
      tone: "Clear",
      language: "English",
      detail_level: "standard",
      objective: "Inform",
      style: "Plain language",
    },
    output_types: ["executive_summary"],
    status,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    artifact_runs: [
      {
        artifact_run_id: 40,
        output_type: "executive_summary",
        status: artifactStatus,
        versions:
          artifactStatus === "pending"
            ? []
            : [
                {
                  id: 50,
                  version_number: 1,
                  source_version_id: 30,
                  source_version_number: 1,
                  content: "Generated after the worker completed.",
                  provider: "openai",
                  model: "gpt-6-luna",
                  prompt_version: "1",
                  prompt_hash: "b".repeat(64),
                  review_status: "draft",
                  created_at: "2026-10-02T00:00:02Z",
                },
              ],
      },
    ],
  };
}

describe("ReviewWorkspace asynchronous generation", () => {
  it("polls the owner-scoped detail endpoint until the artifact result appears", async () => {
    let detailRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("revision-impact")) {
        return Promise.resolve(jsonResponse({}));
      }
      detailRequests += 1;
      return Promise.resolve(
        jsonResponse(
          detailRequests === 1
            ? detail("Generating", "pending")
            : detail("Review Required", "succeeded"),
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <ReviewWorkspace
        transformationId={10}
        onBack={() => {}}
        onTitleChange={() => {}}
        onSourceVersionChange={() => {}}
      />,
    );

    expect(await screen.findByText(/No version yet/)).toBeInTheDocument();
    expect(screen.getByText("Generating")).toBeInTheDocument();
    expect(
      screen.queryByText("Generated after the worker completed."),
    ).toBeNull();

    expect(
      await screen.findByText(
        "Generated after the worker completed.",
        {},
        { timeout: 4000 },
      ),
    ).toBeInTheDocument();
    expect(detailRequests).toBeGreaterThanOrEqual(2);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transformations/10",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
