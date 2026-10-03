export const OUTPUT_TYPES = [
  {
    value: "executive_summary",
    label: "Executive Summary",
    shortLabel: "Summary",
    description: "A decision-ready brief for quick understanding.",
  },
  {
    value: "linkedin_post",
    label: "Professional Post",
    shortLabel: "Post",
    description: "A polished update for a professional audience.",
  },
  {
    value: "x_post",
    label: "X Post",
    shortLabel: "X Post",
    description: "A concise social update for quick public communication.",
  },
  {
    value: "advisory",
    label: "Formal Advisory",
    shortLabel: "Advisory",
    description: "A clear, structured notice for action or awareness.",
  },
  {
    value: "presentation",
    label: "Presentation",
    shortLabel: "Slides",
    description: "A concise slide outline with speaker notes.",
  },
] as const;

export type OutputType = (typeof OUTPUT_TYPES)[number]["value"];
export type DetailLevel = "brief" | "standard" | "detailed";
export type ArtifactRunStatus = "pending" | "running" | "succeeded" | "failed";
export type ReviewStatus = "draft" | "accepted" | "rejected";
export type WorkflowStatus =
  "Draft" | "Generating" | "Review Required" | "Partial Failure" | "Complete";

export type TransformationRequest = {
  source_text: string;
  source_version_id?: number;
  output_types: OutputType[];
  audience: string;
  tone: string;
  language: string;
  detail_level: DetailLevel;
  objective: string;
  style: string;
  supporting_context: string;
};

export type SourceVersion = {
  id: number;
  version_number: number;
  content_hash: string;
  created_at?: string;
};

export type SavedTransformation = {
  status: "saved";
  transformation_run_id: number;
  source_id: number;
  source_version: SourceVersion & { segment_count: number };
  output_types: OutputType[];
};

export type GeneratedArtifactVersion = {
  id: number;
  version_number: number;
  source_version_id: number;
  source_version_number: number;
  content: string;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  prompt_hash: string | null;
  created_at?: string;
};

export type GeneratedArtifact = {
  artifact_run_id: number;
  output_type: OutputType;
  status: ArtifactRunStatus;
  artifact_version: GeneratedArtifactVersion | null;
};

export type DashboardArtifactState = {
  output_type: OutputType;
  status: ArtifactRunStatus | null;
  latest_version_number: number | null;
  review_status: ReviewStatus | null;
};

export type DashboardItem = {
  transformation_run_id: number;
  source_version: SourceVersion;
  output_types: string[];
  artifact_states: DashboardArtifactState[];
  status: WorkflowStatus;
  created_at: string;
  updated_at: string;
};

export type ReviewArtifactVersion = GeneratedArtifactVersion & {
  review_status: ReviewStatus;
  created_at: string;
  context_manifest: ContextManifestSummary | null;
  claim_scan: ClaimScanSummary | null;
};

export type ContextManifestSummary = {
  id: number;
  source_version_id: number;
  source_pack_version_id: number;
  route: string;
  context_profile: string;
  state: string;
  extraction_coverage: string;
  estimated_context_units: number;
  context_budget_units: number;
  region_count: number;
  warnings: string[];
  created_at: string;
};

export type ClaimScanSummary = {
  id: number;
  status: "pending" | "running" | "complete" | "failed" | "needs_review";
  total_batches: number;
  completed_batches: number;
  failed_batches: number;
  needs_review_batches: number;
  claims_found: number;
};

export type ReviewArtifactRun = {
  artifact_run_id: number;
  output_type: OutputType;
  status: ArtifactRunStatus;
  versions: ReviewArtifactVersion[];
  context_manifest: ContextManifestSummary | null;
};

export type TransformationDetail = {
  transformation_run_id: number;
  source_version: SourceVersion;
  controls: Record<string, string>;
  output_types: string[];
  status: WorkflowStatus;
  created_at: string;
  updated_at: string;
  artifact_runs: ReviewArtifactRun[];
};

export type EvidenceLink = {
  id: number;
  artifact_version_id: number;
  claim_text: string;
  source_version_id: number;
  source_segment_id: number | null;
  source_quote: string | null;
  source_locator: string | null;
  status: "linked" | "support_not_located";
  created_at: string;
};

export type SourceVersionContent = SourceVersion & {
  source_text: string;
};

export type DiscrepancyFinding = {
  id: number;
  source_version_id: number;
  artifact_version_a_id: number;
  artifact_version_b_id: number;
  statement_a: string;
  statement_b: string;
  discrepancy_type: string;
  explanation: string;
  review_status: "open" | "dismissed";
  created_at: string;
};

export type SourceSegmentChange = {
  change_type: "added" | "removed" | "changed";
  locator: string;
  old_text: string | null;
  new_text: string | null;
};

export type AffectedArtifact = {
  artifact_run_id: number;
  artifact_version_id: number;
  output_type: string;
  artifact_version_number: number;
  evidence_claims: string[];
};

export type SourceRevisionStatus = {
  transformation_run_id: number;
  parent_source_version: SourceVersion | null;
  source_version: SourceVersion;
  changes: SourceSegmentChange[];
  potentially_affected_artifacts: AffectedArtifact[];
};

export type SourceFileMetadata = {
  filename: string;
  character_count: number;
  ocr_used: boolean;
  source_version_id?: number;
};

export type PresentationSlide = {
  title: string;
  key_message: string;
  bullets: string[];
  visual_recommendation: string;
  speaker_notes: string;
};

export type PresentationDocument = {
  title: string;
  slides: PresentationSlide[];
};

export type WorkspaceScreen = "dashboard" | "new" | "review";
export type InspectorTab = "evidence" | "warnings" | "versions" | "details";
