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
  {
    value: "infographic",
    label: "Infographic",
    shortLabel: "Infographic",
    description: "An editable structured infographic specification.",
  },
  {
    value: "video_package",
    label: "Video Package",
    shortLabel: "Video",
    description: "An editable video production package with scenes and script.",
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
  context_manifest_id?: number | null;
  source_version_number: number;
  content: string;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  prompt_hash: string | null;
  artifact_schema_version?: string | null;
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

export type EvidenceState =
  | "quote_located"
  | "supported"
  | "partial"
  | "contradicted"
  | "missing"
  | "ambiguous"
  | "conflict"
  | "non_factual";

export type EvidenceAssessment = {
  id: number;
  artifact_version_id: number;
  material_claim_id: number;
  context_manifest_id: number | null;
  knowledge_assertion_id: number | null;
  source_region_id: number | null;
  evidence_state: EvidenceState;
  source_quote: string | null;
  quote_start: number | null;
  quote_end: number | null;
  assessment_method: "mechanical" | "semantic_verifier" | "human";
  verifier_profile: string;
  verifier_profile_version: string;
  reason_code: string | null;
  review_state: "needs_review" | "reviewed";
  adjudicated_state: EvidenceState | null;
  reviewed_at: string | null;
  created_at: string;
};

export type ArtifactBlockDependency = {
  id: number;
  source_region_id: number;
  source_content_hash: string;
  dependency_hash: string;
  dependency_kind: "quote" | "assertion" | "lineage";
  origin: "proposal" | "evidence" | "carried_forward";
};

export type ArtifactBlockLineage = {
  id: number;
  block_key: string;
  ordinal: number;
  block_type: string;
  visible_text: string;
  content_hash: string;
  material_claim_ids: number[];
  dependencies: ArtifactBlockDependency[];
};

export type MaterialClaimLineage = {
  id: number;
  proposition: string;
  artifact_quote: string;
  block_mapping_state: "validated" | "ambiguous" | "unmapped" | null;
  block_keys: string[];
};

export type LineageProposal = {
  id: number;
  block_key: string;
  claim_text: string;
  material_claim_id: number | null;
  source_region_id: number | null;
  knowledge_assertion_id: number | null;
  source_quote: string;
  validation_state:
    | "validated"
    | "invalid_scope"
    | "invalid_region"
    | "invalid_assertion"
    | "invalid_span"
    | "ambiguous"
    | "unresolved";
  rejection_reason: string | null;
  validated_quote_start: number | null;
  validated_quote_end: number | null;
};

export type ArtifactReviewDecision = {
  id: number;
  artifact_version_id: number;
  decision: "accepted" | "rejected";
  note: string | null;
  created_at: string;
};

export type ArtifactLineage = {
  artifact_version_id: number;
  lineage_available: boolean;
  blocks: ArtifactBlockLineage[];
  claims: MaterialClaimLineage[];
  proposals: LineageProposal[];
  assessments: EvidenceAssessment[];
  review_decisions: ArtifactReviewDecision[];
};

export type SourceVersionContent = SourceVersion & {
  source_text: string;
};

export type DiscrepancyFinding = {
  id: number;
  source_version_id: number;
  artifact_version_a_id: number;
  artifact_version_b_id: number;
  material_claim_a_id: number | null;
  material_claim_b_id: number | null;
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
  impact_state?: "unaffected" | "affected" | "needs_review" | "unknown";
  affected_block_keys?: string[];
  review_block_keys?: string[];
  unknown_block_keys?: string[];
  targeted_update_available?: boolean;
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
  extraction_coverage?: "complete" | "partial" | "unavailable";
  extraction_details?: Record<string, unknown> | null;
};

export type SourceRegionInspection = {
  id: number;
  source_segment_id: number | null;
  ordinal: number;
  locator: string;
  region_type: string;
  page_number: number | null;
  text: string | null;
  locator_kind: string | null;
  locator_metadata: Record<string, unknown> | null;
};

export type SourceAssetInspection = {
  id: number;
  source_kind: "text" | "file" | "url" | "image" | "audio" | "video";
  media_type: string;
  original_filename: string | null;
  byte_size: number;
  content_hash: string;
  provenance_url: string | null;
  extraction_method: string;
  extraction_profile: string;
  extraction_profile_version: number;
  extraction_coverage: "complete" | "partial" | "unavailable";
  extraction_details: Record<string, unknown> | null;
  preview_url: string | null;
  download_url: string | null;
  rights_basis: string | null;
  consent_state: string | null;
  consent_required: boolean | null;
  attribution: string | null;
  regions: SourceRegionInspection[];
};

export type SourcePackInspection = {
  id: number;
  title: string | null;
  created_at: string;
  versions: {
    id: number;
    source_version_id: number;
    version_number: number;
    parent_source_pack_version_id: number | null;
    content_hash: string;
    created_at: string;
    assets: SourceAssetInspection[];
    memberships: {
      id: number;
      source_version_id: number;
      source_asset_id: number;
      ordinal: number;
      role: string;
      asset: SourceAssetInspection;
    }[];
  }[];
};

export type MediaAsset = {
  id: number;
  purpose: string;
  media_type: string;
  byte_size: number;
  content_hash: string;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  created_at: string;
  preview_url: string;
  download_url: string;
};

export type MediaRights = {
  rights_basis: string;
  consent_state: string;
  consent_required: boolean;
  attribution: string | null;
  eligible_for_composition: boolean;
};

export type MediaTaskAsset = MediaAsset;

export type MediaTask = {
  id: number;
  task_key: string;
  task_kind: string;
  ordinal: number | null;
  status: string;
  failure_code: string | null;
  job_status: string | null;
  attempts: number;
  assets: MediaTaskAsset[];
};

export type MediaMetric = {
  operation_type: string;
  elapsed_ms: number;
  input_bytes: number;
  output_bytes: number;
  output_duration_ms: number | null;
  tool_version: string;
  external_api_cost: number | null;
};

export type MediaReview = {
  reviewer_user_id: number;
  primary_asset_hash: string;
  decision: "approved" | "rejected";
  note: string | null;
  created_at: string;
};

export type MediaRender = {
  id: number;
  artifact_version_id: number;
  artifact_family: "infographic" | "video_package";
  renderer_profile: string;
  renderer_version: string;
  render_plan: Record<string, unknown>;
  status: string;
  failure_code: string | null;
  created_at: string;
  completed_at: string | null;
  primary_asset: MediaAsset | null;
  tasks: MediaTask[];
  metrics: MediaMetric[];
  reviews: MediaReview[];
  review_copy: string;
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

export type InfographicBlock =
  | { type: "section"; heading: string; body: string }
  | {
      type: "callout";
      label: string;
      value: string;
      explanation: string;
    }
  | {
      type: "data";
      heading: string;
      rows: { label: string; value: string; note: string }[];
    };

export type InfographicDocument = {
  title: string;
  subtitle: string;
  key_message: string;
  blocks: InfographicBlock[];
  visual_direction: string;
};

export type VideoScene = {
  title: string;
  narration: string;
  on_screen_text: string[];
  visual_direction: string;
  transition_notes: string;
};

export type VideoPackageDocument = {
  title: string;
  concept: string;
  scenes: VideoScene[];
};

export type WorkspaceScreen = "dashboard" | "new" | "review";
export type InspectorTab = "evidence" | "warnings" | "versions" | "details";
