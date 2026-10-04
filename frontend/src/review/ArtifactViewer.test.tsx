import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReviewArtifactRun, ReviewArtifactVersion } from "../types";
import { ArtifactViewer } from "./ArtifactViewer";

const styles = readFileSync("src/styles.css", "utf8");

afterEach(cleanup);

const guidance = "DO_NOT_SHOW_THIS_LAYOUT_INSTRUCTION";
const presentation = {
  title: "Project Asteria",
  slides: [
    {
      title: "Pilot scope",
      key_message: "The pilot starts in November.",
      bullets: ["18 wards", "Maya Sen"],
      visual_recommendation: "Launch scope facts in cards.",
      speaker_notes: "Explain the scope.",
    },
    {
      title: "Review milestones",
      key_message: "The review follows the launch.",
      bullets: ["15 November launch", "15 February review"],
      visual_recommendation: guidance,
      speaker_notes: "Explain the dates.",
    },
  ],
};

function renderViewer() {
  const version = {
    id: 50,
    version_number: 2,
    source_version_id: 30,
    source_version_number: 1,
    content: JSON.stringify(presentation),
    provider: "openai",
    model: "gpt-6-luna",
    prompt_version: "1",
    prompt_hash: "a".repeat(64),
    review_status: "draft",
    created_at: "2026-10-02T00:00:00Z",
    context_manifest: null,
    claim_scan: null,
  } as ReviewArtifactVersion;
  const previousVersion = {
    ...version,
    id: 49,
    version_number: 1,
    content: "Earlier draft",
    review_status: "accepted",
  } as ReviewArtifactVersion;
  const artifact = {
    artifact_run_id: 40,
    output_type: "presentation",
    status: "succeeded",
    versions: [previousVersion, version],
  } as ReviewArtifactRun;
  const onSave = vi.fn();
  const onSelectVersion = vi.fn();

  render(
    <ArtifactViewer
      artifact={artifact}
      version={version}
      versions={artifact.versions}
      selectedVersionId={version.id}
      onSelectVersion={onSelectVersion}
      projectTitle="Project Asteria"
      currentSourceVersion={1}
      isLatest
      busy={false}
      exportStatus={null}
      onEdit={() => {}}
      onSave={onSave}
      onCancelEdit={() => {}}
      onRegenerate={() => {}}
      onRetry={() => {}}
      onReviewStatus={() => {}}
      onCopy={() => {}}
      onDownload={() => {}}
      onPowerpointExport={() => {}}
      onTraceability={() => {}}
    />,
  );
  return { onSave, onSelectVersion };
}

function renderExecutiveSummary() {
  const version = {
    id: 51,
    version_number: 1,
    source_version_id: 30,
    source_version_number: 1,
    content: "## Executive Summary\n\nThe pilot begins in November.",
    provider: "openai",
    model: "gpt-6-luna",
    prompt_version: "1",
    prompt_hash: "a".repeat(64),
    review_status: "draft",
    created_at: "2026-10-02T00:00:00Z",
    context_manifest: null,
    claim_scan: null,
  } as ReviewArtifactVersion;
  const artifact = {
    artifact_run_id: 41,
    output_type: "executive_summary",
    status: "succeeded",
    versions: [version],
  } as ReviewArtifactRun;
  render(
    <ArtifactViewer
      artifact={artifact}
      version={version}
      versions={artifact.versions}
      selectedVersionId={version.id}
      onSelectVersion={() => {}}
      projectTitle="Project Asteria"
      currentSourceVersion={1}
      isLatest
      busy={false}
      exportStatus={null}
      onEdit={() => {}}
      onSave={() => {}}
      onCancelEdit={() => {}}
      onRegenerate={() => {}}
      onRetry={() => {}}
      onReviewStatus={() => {}}
      onCopy={() => {}}
      onDownload={() => {}}
      onPowerpointExport={() => {}}
      onTraceability={() => {}}
    />,
  );
}

describe("presentation artifact view and editor", () => {
  it("uses the selected layout and keeps guidance off the slide canvas", () => {
    renderViewer();

    expect(screen.getByText("18 wards")).toBeInTheDocument();
    expect(
      document.querySelector(".slide-canvas")?.getAttribute("data-layout"),
    ).toBe("fact_cards");
    expect(screen.queryByText("Visual direction")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Launch scope facts in cards."),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next slide" }));
    expect(
      document.querySelector(".slide-canvas")?.getAttribute("data-layout"),
    ).toBe("standard");
    expect(screen.queryByText(guidance)).not.toBeInTheDocument();
  });

  it("switches between immutable versions from the artifact header", () => {
    const { onSave, onSelectVersion } = renderViewer();
    fireEvent.click(
      screen
        .getByRole("group", { name: "Artifact versions" })
        .parentElement!.querySelector("summary")!,
    );
    expect(
      screen.getByRole("button", { name: /Version 1 Accepted/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Version 1 Accepted/ }));
    expect(onSelectVersion).toHaveBeenCalledWith(49);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("keeps primary actions visible and secondary actions available in More", () => {
    renderViewer();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Traceability" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "More artifact actions" }),
    );
    expect(screen.getByRole("button", { name: "Copy artifact" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Download Markdown" }),
    ).toBeVisible();
  });

  it("provides mobile thumbnail strips and a stacked editor structure", () => {
    renderViewer();
    expect(
      document.querySelector(".presentation-viewer > .slide-rail"),
    ).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(
      document.querySelector(".presentation-editor__workspace > .slide-rail"),
    ).not.toBeNull();
    expect(styles).toContain(".presentation-viewer > .slide-rail");
    expect(styles).toContain(".presentation-editor__workspace > .slide-rail");
    expect(styles).toContain("grid-template-columns: minmax(0, 1fr)");
  });

  it("keeps editable layout guidance in a disclosure and exposes all controls", () => {
    const { onSave } = renderViewer();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);

    fireEvent.click(screen.getByRole("button", { name: /Slide 2/ }));
    const guidanceDisclosure = screen.getByText("Layout guidance");
    expect(guidanceDisclosure.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(guidanceDisclosure);
    expect(screen.getByLabelText("Visual recommendation")).toHaveValue(
      guidance,
    );
    expect(screen.getByLabelText("Speaker notes")).toHaveValue(
      "Explain the dates.",
    );

    expect(screen.getByLabelText("Title")).toHaveValue("Review milestones");
    expect(screen.getByLabelText("Key message")).toHaveValue(
      "The review follows the launch.",
    );
    expect(screen.getByLabelText("Bullets (one per line)")).toHaveValue(
      "15 November launch\n15 February review",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save version" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("renders the matching Markdown title only once in a text artifact", () => {
    renderExecutiveSummary();

    expect(
      screen.getAllByRole("heading", { name: "Executive Summary" }),
    ).toHaveLength(1);
    expect(
      screen.getByText("The pilot begins in November."),
    ).toBeInTheDocument();
  });
});
