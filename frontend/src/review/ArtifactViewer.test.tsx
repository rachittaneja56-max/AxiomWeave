import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReviewArtifactRun, ReviewArtifactVersion } from "../types";
import { ArtifactViewer } from "./ArtifactViewer";

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
    version_number: 1,
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
  const artifact = {
    artifact_run_id: 40,
    output_type: "presentation",
    status: "succeeded",
    versions: [version],
  } as ReviewArtifactRun;
  const onSave = vi.fn();

  render(
    <ArtifactViewer
      artifact={artifact}
      version={version}
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
  return { onSave };
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
