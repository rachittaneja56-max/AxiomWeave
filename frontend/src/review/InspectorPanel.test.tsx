import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ArtifactLineage,
  EvidenceLink,
  ReviewArtifactRun,
  ReviewArtifactVersion,
  SourceVersion,
  TransformationDetail,
} from "../types";
import { InspectorPanel } from "./InspectorPanel";

afterEach(cleanup);

const sourceVersion = {
  id: 30,
  version_number: 1,
  content_hash: "a".repeat(64),
  created_at: "2026-10-02T00:00:00Z",
} as SourceVersion;

function panelProps({ complete = false }: { complete?: boolean } = {}) {
  const claim = {
    id: 70,
    proposition: "The pilot initially covers 18 wards.",
    artifact_quote: "The pilot initially covers 18 wards.",
    block_mapping_state: "validated" as const,
    block_keys: ["paragraph:1"],
  };
  const quote = "The pilot initially covers eighteen wards.";
  const version = {
    id: 50,
    version_number: 1,
    source_version_id: sourceVersion.id,
    source_version_number: 1,
    content: "The pilot initially covers 18 wards.",
    provider: "openai",
    model: "gpt-6-luna",
    prompt_version: "1",
    prompt_hash: "b".repeat(64),
    review_status: "draft",
    created_at: "2026-10-02T00:00:00Z",
    context_manifest: null,
    claim_scan: complete
      ? {
          id: 80,
          status: "complete",
          total_batches: 1,
          completed_batches: 1,
          failed_batches: 0,
          needs_review_batches: 0,
          claims_found: 1,
        }
      : null,
  } as ReviewArtifactVersion;
  const artifact = {
    artifact_run_id: 40,
    output_type: "executive_summary",
    status: "succeeded",
    versions: [version],
  } as ReviewArtifactRun;
  const detail = {
    transformation_run_id: 10,
    source_version: sourceVersion,
    controls: {},
    output_types: ["executive_summary"],
    status: "Review Required",
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    artifact_runs: [artifact],
  } as TransformationDetail;
  const lineage: ArtifactLineage = {
    artifact_version_id: version.id,
    lineage_available: true,
    blocks: [
      {
        id: 90,
        block_key: "paragraph:1",
        ordinal: 1,
        block_type: "paragraph",
        visible_text: "The pilot initially covers 18 wards.",
        content_hash: "c".repeat(64),
        material_claim_ids: complete ? [claim.id] : [],
        dependencies: [
          {
            id: 91,
            source_region_id: 92,
            source_content_hash: "d".repeat(64),
            dependency_hash: "e".repeat(64),
            dependency_kind: "quote",
            origin: "evidence",
          },
        ],
      },
      {
        id: 93,
        block_key: "paragraph:2",
        ordinal: 2,
        block_type: "paragraph",
        visible_text: "The launch is scheduled for November.",
        content_hash: "f".repeat(64),
        material_claim_ids: [],
        dependencies: [],
      },
    ],
    claims: complete ? [claim] : [],
    proposals: [],
    assessments: complete
      ? [
          {
            id: 100,
            artifact_version_id: version.id,
            material_claim_id: claim.id,
            context_manifest_id: null,
            knowledge_assertion_id: null,
            source_region_id: 92,
            evidence_state: "supported",
            source_quote: quote,
            quote_start: null,
            quote_end: null,
            assessment_method: "semantic_verifier",
            verifier_profile: "test",
            verifier_profile_version: "1",
            reason_code: null,
            review_state: "needs_review",
            adjudicated_state: null,
            reviewed_at: null,
            created_at: "2026-10-02T00:00:00Z",
          },
        ]
      : [],
    review_decisions: [],
  };
  const evidence: EvidenceLink[] = [];
  return {
    activeTab: "evidence" as const,
    onTabChange: () => {},
    detail,
    sourceVersion,
    artifact,
    version,
    selectedVersionId: version.id,
    evidence,
    lineage,
    warnings: [],
    warningsChecked: false,
    partialWarnings: false,
    checkingWarnings: false,
    busy: false,
    onLoadEvidence: () => {},
    onAnalyzeEvidence: () => {},
    onVerifyEvidence: () => {},
    onReviewEvidence: () => {},
    onResumeClaimScan: () => {},
    onViewSource: () => {},
    onCheckWarnings: () => {},
    onDismissWarning: () => {},
    onSelectVersion: () => {},
  };
}

describe("traceability evidence panel", () => {
  it("shows an analysis empty state before scanning and hides raw lineage by default", () => {
    render(<InspectorPanel {...panelProps()} />);

    expect(
      screen.getByText(
        "Claim analysis has not been completed for this version.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Analyze claims" }),
    ).toBeInTheDocument();
    const disclosure = screen.getByText("Technical lineage");
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    expect(
      screen.getByText("paragraph:1", { selector: "code" }).closest("details"),
    ).not.toHaveAttribute("open");
    fireEvent.click(disclosure);
    expect(screen.getByText("Paragraph 1")).toBeInTheDocument();
    expect(screen.getByText("paragraph:1")).toBeInTheDocument();
  });

  it("shows batch progress while claim analysis is running", () => {
    const props = panelProps();
    props.version.claim_scan = {
      id: 81,
      status: "running",
      total_batches: 3,
      completed_batches: 2,
      failed_batches: 0,
      needs_review_batches: 0,
      claims_found: 0,
    };
    render(<InspectorPanel {...props} />);

    expect(screen.getByText("Analyzing claims…")).toBeInTheDocument();
    expect(screen.getByText("2 / 3 batches complete")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Analyze claims" }),
    ).not.toBeInTheDocument();
  });

  it("renders claim cards with readable assessment and sends the exact quote to source view", () => {
    const props = panelProps({ complete: true });
    const onViewSource = vi.fn();
    render(<InspectorPanel {...props} onViewSource={onViewSource} />);

    expect(
      screen.getByText("The pilot initially covers 18 wards.", {
        selector: ".claim-card__text",
      }),
    ).toBeInTheDocument();
    expect(document.querySelector(".evidence-chip")).toHaveTextContent(
      "Supported",
    );
    expect(screen.getByText("Semantic review")).toBeInTheDocument();
    expect(screen.getByText("Needs human review")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show in source" }));
    expect(onViewSource).toHaveBeenCalledWith(
      sourceVersion.id,
      "The pilot initially covers eighteen wards.",
    );
  });
});
