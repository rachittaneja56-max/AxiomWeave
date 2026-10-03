import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

function structuredDetail(
  outputType: "infographic" | "video_package",
  content: string,
) {
  return {
    ...detail("Review Required", "succeeded"),
    output_types: [outputType],
    artifact_runs: [
      {
        artifact_run_id: 40,
        output_type: outputType,
        status: "succeeded",
        context_manifest: null,
        versions: [
          {
            id: 50,
            version_number: 1,
            source_version_id: 30,
            source_version_number: 1,
            context_manifest_id: 70,
            artifact_schema_version: "1",
            content,
            provider: "openai",
            model: "gpt-6-luna",
            prompt_version: "1",
            prompt_hash: "b".repeat(64),
            review_status: "draft",
            created_at: "2026-10-02T00:00:02Z",
            context_manifest: null,
            claim_scan: null,
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

  it.each([
    [
      "infographic" as const,
      {
        title: "Clinic facts",
        subtitle: "A short information card",
        key_message: "The clinic opens on Monday.",
        blocks: [
          {
            type: "callout",
            label: "Opening day",
            value: "Monday",
            explanation: "The clinic opens on Monday.",
          },
        ],
        visual_direction: "Use a simple calendar illustration.",
      },
    ],
    [
      "video_package" as const,
      {
        title: "Clinic opening update",
        concept: "Share the clinic opening day.",
        scenes: [
          {
            title: "Opening day",
            narration: "The clinic opens on Monday.",
            on_screen_text: ["Opens Monday"],
            visual_direction: "Show the clinic entrance.",
            transition_notes: "Fade to the closing card.",
          },
        ],
      },
    ],
  ])(
    "displays, edits, and saves the structured %s family",
    async (outputType, spec) => {
      const content = JSON.stringify(spec);
      const fetchMock = vi.fn(
        (input: RequestInfo | URL, init?: RequestInit) => {
          if (String(input).includes("revision-impact"))
            return Promise.resolve(jsonResponse({}));
          if (String(input) === "/api/transformations/10")
            return Promise.resolve(
              jsonResponse(structuredDetail(outputType, content)),
            );
          if (
            String(input) === "/api/artifact-runs/40/versions" &&
            init?.method === "POST"
          ) {
            return Promise.resolve(jsonResponse({}));
          }
          throw new Error(`Unexpected request: ${String(input)}`);
        },
      );
      vi.stubGlobal("fetch", fetchMock);

      render(
        <ReviewWorkspace
          transformationId={10}
          initialOutputType={outputType}
          onBack={() => {}}
          onTitleChange={() => {}}
          onSourceVersionChange={() => {}}
        />,
      );

      expect(
        (
          await screen.findAllByText(
            outputType === "infographic"
              ? "Editable infographic specification"
              : "Editable video production package",
          )
        ).length,
      ).toBe(2);
      if (outputType === "infographic") {
        expect(
          screen.getAllByText(/The clinic opens on Monday/).length,
        ).toBeGreaterThan(0);
        expect(
          screen.getByText("Use a simple calendar illustration."),
        ).toBeInTheDocument();
      } else {
        expect(
          screen.getAllByText(/The clinic opens on Monday/).length,
        ).toBeGreaterThan(0);
        expect(
          screen.getByText("Show the clinic entrance."),
        ).toBeInTheDocument();
      }
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      const titleInput = document.getElementById(
        outputType === "infographic"
          ? "infographic-title"
          : "video-package-title",
      ) as HTMLInputElement;
      expect(titleInput).toBeInTheDocument();
      fireEvent.change(titleInput, {
        target: { value: "Edited structured title" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save version" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/api/artifact-runs/40/versions",
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const saveCall = fetchMock.mock.calls.find(
        ([path, request]) =>
          String(path) === "/api/artifact-runs/40/versions" &&
          request?.method === "POST",
      );
      expect(saveCall).toBeDefined();
      const savedContent = JSON.parse(String(saveCall?.[1]?.body));
      expect(JSON.parse(savedContent.content).title).toBe(
        "Edited structured title",
      );
    },
  );
});
