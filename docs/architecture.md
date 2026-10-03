# AxiomWeave architecture

## Identity and request boundary

```text
Username + password -> Argon2id verification -> local user
  -> HttpOnly session cookie -> owner-scoped React workspace
```

The backend verifies passwords with Argon2id, maps the normalized username to a local user, and issues a separate eight-hour application session. Only a SHA-256 digest of the random session token is stored. The cookie is HttpOnly, SameSite=Lax, and Secure outside development. Login failures use a generic response and a persistent username-keyed throttle. Logout revokes the session. User IDs come from the authenticated session, never request JSON. Password authentication is not phishing-resistant and is the selected Tier-A demo method. Source text and supporting context are treated as untrusted data.

## Source, brief, and generated artifacts

```text
Paste / TXT / MD / DOCX / PDF / PNG / JPEG / WAV / MP3 / M4A / MP4 / one public URL
  -> for URLs: safe bounded HTTP fetch -> HTML/main-content extraction
  -> text, document, image, audio, or video validation and bounded extraction
  -> PDF OCR/Vision fallback only for PDF pages with under 40 usable native characters
  -> image OCR/description, timestamped audio transcription, and sampled video frames when an extractor is configured
  -> owner-scoped SourcePack -> immutable SourcePackVersion
  -> immutable source memberships (PRIMARY / SUPPORTING / STYLE / REFERENCE / OPERATOR_CONTEXT)
  -> exact SourceVersion + SourceAsset -> addressable SourceRegions
  -> compatibility SourceVersion + SHA-256 + SourceSegments
  -> TransformationRun (separate context and communication controls)
  -> ArtifactRun per selected format -> immutable ArtifactVersion history
```

All seven output types are executable: executive summary, LinkedIn post, X Post, formal advisory, presentation, infographic, and video package. Each selected family receives an independent durable Job and ContextManifest, so failures and retries remain isolated. X Post currently uses the compatible single-post contract, limited to 220 provider output tokens and 280 Unicode code points. A centralized server-owned contract defines each family's schema version, prompt metadata, token budget, validation, serialization, and readable text projection. New versions store their artifact schema version; historical rows remain nullable rather than receiving invented metadata. Existing text families stay plain text, and Presentation keeps its established `PresentationSpec` JSON shape. Infographic creates an editable bounded `InfographicSpec`; Video Package creates an editable bounded `VideoPackageSpec` with ordered scenes. Phase 5 adds deterministic private media derivatives while preserving these editable source specifications.

URL imports accept one public HTTP/HTTPS page at a time. The fetcher validates DNS results and pins the connection to a validated public IP, manually revalidates up to three redirects, streams at most 2 MiB, and extracts readable HTML or plain text. File and URL imports create a SourcePackVersion when extraction succeeds; the composer reuses that owned version when saving the transformation. Pasted text creates its SourcePackVersion when the transformation is saved. If an imported source is edited in the composer, the app appends a new version and keeps the imported version intact. URL assets retain the validated final URL as provenance and do not fabricate a binary object. The importer does not crawl or execute page scripts.

## OpenAI generation boundary

```text
FastAPI generation / analysis routes -> provider protocol -> OpenAI Responses API
```

The server owns model choice and API key. Primary artifact generation and targeted updates use `gpt-6-luna`; evidence proposals, discrepancy analysis, and scanned-page OCR use the utility model (`SIH_OPENAI_UTILITY_MODEL`, default `gpt-5-nano`). Generation and analysis calls have code-owned output-token limits. Primary and utility structured generation uses low reasoning effort; OCR uses a separate bounded transcription call. All Responses API requests set `store=False`. Structured responses use the exact server-owned Pydantic model for Presentation, Infographic, and Video Package, plus the existing evidence and discrepancy schemas. Incomplete provider responses fail without persisting a successful artifact version. Provider errors are converted to safe API errors; raw provider output and credentials are not returned as diagnostics.

Document uploads are bounded: text is capped at 80 KiB; DOCX and PDF at 8 MiB; PDFs at 20 pages; OCR fallback at 8 pages; normalized extracted text at 20,000 characters. PDF text retains `# Page N` markers and its regions retain page locators. Encrypted, corrupt, and empty PDFs are rejected. Source-image uploads are capped at 10 MiB, 4,000 pixels per edge, and 16 megapixels; audio is capped at 16 MiB/60 seconds; MP4 video is capped at 100 MiB/180 seconds with frames sampled every five seconds, at most 36 frames. No live Vision or ASR provider is selected, so extraction can explicitly remain unavailable while original bytes and non-text locators are retained. Original uploads are stored under server-generated keys in the private local directory configured by `SIH_PRIVATE_ASSET_DIR`; that directory is not served by FastAPI. Authenticated owner-scoped preview and download routes read through the private storage boundary. Rendered OCR images are temporary. If the database transaction fails, the app attempts to delete the prepared file; a filesystem failure during that cleanup can leave an unreferenced private file for manual cleanup. The storage boundary is local-development only; no production object-store adapter is deployed.

Each pack snapshot has one `PRIMARY` member; an ordered membership row names the exact source version and asset assigned to that snapshot. Additional sources may be `SUPPORTING`, `STYLE`, `REFERENCE`, or `OPERATOR_CONTEXT`. The server validates the role, source/asset pairing, and common owner before writing memberships. The deterministic role policy permits PRIMARY to ground facts; SUPPORTING can ground or contextualize, but conflicts with PRIMARY require review rather than silent override; STYLE controls presentation only; REFERENCE is non-factual by default; OPERATOR_CONTEXT controls the task, not source truth. This policy does not implement semantic conflict detection or resolution.

The additive Phase 1B migrations backfill each existing `Source`, `SourceVersion`, and `SourceSegment` into a SourcePack, SourcePackVersion, text SourceAsset, SourceRegion, and one `PRIMARY` membership linking the exact legacy version and asset. Historical raw uploads are not reconstructed. New source writes go through one snapshot writer that creates the pack records, membership snapshot, and required legacy projection in the same database transaction. A revision appends a pack version and carries forward non-primary members unless its server caller explicitly supplies a replacement membership set. Existing generation, evidence, and revision code continues to read the legacy projection. The old asset-level authority column remains only for migration compatibility; membership roles are canonical.

## Phase 2 context, claims, and retrieval

Each newly queued generation Job receives an immutable `ContextManifest` in the same transaction. The manifest records its exact SourcePackVersion and SourceVersion, route/profile versions, query-construction and budget-policy versions, estimate, reserved margin, extraction coverage, warnings, and region-level entries with role, locator, and content hash. Database triggers protect manifests and entries against direct SQL updates or deletes. The worker validates and renders those stored entries; it does not rerun retrieval. The resulting `ArtifactVersion` points to the same manifest. Historical jobs and artifact versions remain nullable because no historical selection is fabricated.

R0 is the generation baseline. The versioned `context-chars-v1` policy estimates Unicode code points, admits all eligible PRIMARY and SUPPORTING regions up to a 20,000-character context budget, and reserves 5,000 units for output/schema/evidence overhead. The estimate is not provider tokenization. Ordinary single-source R0 preserves the full legacy primary source text. Supporting regions carry role, source identity/version, and locator labels. Partial extraction remains visible. If R0 exceeds its bound and no profile is admitted, the manifest requires review; content is not silently truncated.

Material-claim scans split immutable artifact communication text into deterministic bounded batches. For structured families, the exact deterministic human-readable projection is stored with the scan and scanned instead of raw JSON syntax. Successful batches persist independently and retries process only incomplete batches. Scan status and UI coverage come from total/completed/failed/needs-review batches, with no global claim-count cap. `KnowledgeAssertion` rows are candidate propositions tied to exact regions and exact quote spans when available. Provenance validation does not establish entailment, completeness, or truth; invalid spans remain unresolved and require review. `KnowledgeRelation` is storage only and is not traversed during generation.

The PostgreSQL retrieval repository filters by owner, exact SourcePackVersion, membership role, source-version pairing, asset extraction state, and exact SourceRegion. PostgreSQL native FTS uses the language-neutral `simple` configuration and is not described as BM25. The predeclared four-pack/six-task fixture measured top-2 FTS recall of 2/7 required regions and 1/4 qualifiers, with four task misses. FTS used 117 of R0's 785 source-region characters, an 85.1% reduction, and remains an unpromoted candidate. Character counts cover original region text only; they exclude role labels and provider schema overhead. Exact pgvector and fixed RRF verify ranking and manifest mechanics only; without an approved semantic embedding profile, vector/hybrid quality is not evaluated. Full fixture metrics and limitations are in `backend/evals/retrieval/README.md`.

## Phase 4 lineage, evidence, review, and consistency

Every new artifact version receives deterministic addressable ArtifactBlocks, a durable independent ClaimScan, and optional generation-time lineage proposals. Model-supplied IDs and quotes remain untrusted until the server checks exact ownership, SourcePackVersion, ContextManifest membership and role, assertion scope, and source offsets. Validated `MaterialClaimBlock` mappings can drive content-addressed ArtifactBlock dependencies. Legacy EvidenceLinks remain compatibility records; they do not mean semantic support.

Claim coverage and evidence state are separate. Mechanical `quote_located` records exact quotation location only. A bounded structured verifier can assess `supported`, `partial`, `contradicted`, `missing`, `ambiguous`, `conflict`, or `non_factual` for exact claims and manifest regions. Verifier output is not ground truth; all assessments start reviewable and human adjudication is stored separately. Cross-artifact findings reference exact sibling versions and claims and never select a winning version or rewrite content. Artifact review decisions are historical records attached to exact immutable versions; user acceptance does not certify factual accuracy.

Historical artifact versions remain lineage-unavailable until re-analysis. The Phase 4 migration does not invent historical blocks, lineage proposals, evidence assessments, review decisions, or source-region alignments. Existing EvidenceLink and DiscrepancyFinding data remain in place.

## Phase 5 deterministic media and multimodal source boundary

```text
exact ArtifactVersion
  -> immutable MediaRender plan snapshot
  -> durable media_cpu MediaTask jobs
  -> private SVG/PNG or per-scene PNG assets
  -> FFmpeg composition + WebVTT captions
  -> ffprobe validation -> private MP4 asset
  -> exact-render human media decision
```

Each `MediaRender` is owner-scoped and fixed to one immutable `ArtifactVersion`; its plan hash, family, renderer profile, and renderer version cannot be changed after creation. `MediaTask` targets extend the existing Job table and `media_cpu` claim path. Video scene cards run as bounded independent jobs. The compose task is created only after every scene output commits and has a `JobDependency` edge to each successful scene job. A failed scene marks the render `partial_failure`; retry requeues only failed work and preserves successful scene assets. Exact content-addressed scene frames may be reused only for the same owner, artifact version, renderer profile, and identical scene inputs.

The infographic renderer uses fixed text/data layouts to create escaped static SVG and PyMuPDF PNG output; values remain text from the spec and visual direction does not fetch or fabricate facts. Video v1 uses 1280×720 at 30 fps, deterministic scene cards, hard cuts, bounded 3–15 second text-pacing estimates that users can override, and scene narration/on-screen text as WebVTT sidecars. No narration asset means a silent audio track is muxed; it does not imply generated speech. Optional uploaded scene images and narration audio use the same private asset store and require explicitly eligible rights metadata before composition. Image bounds are 10 MiB, 4,000 pixels per edge, and 16 megapixels; audio is 16 MiB/60 seconds; total video is at most 180 seconds/256 MiB. These are operational resource caps, not quality thresholds. FFmpeg receives an argv array with shell execution disabled, local files only, bounded timeouts, temporary working directories, and generated filenames. FFprobe validates stream type, dimensions, frame rate, and duration. Tool versions, task timing, byte counts, output duration, and external API cost are persisted as media metrics.

Original source media remains a `SourceAsset`; OCR/transcript/frame regions are `SourceRegion` rows with bbox or timestamp metadata and modality-specific extraction profiles/coverage. Extracted text enters the existing immutable `SourceVersion` and `ContextManifest` path. If extraction is unavailable, the retained projection is an explicit placeholder, no factual `SourceRegion` is created, and context planning reports the coverage gap. Source image/audio/video bytes are not used as factual labels by the renderer. No live image, video, Vision, ASR, TTS, or other generated-video provider is selected in Phase 5.

`MediaRightsRecord` records a user/system-controlled rights basis, consent state, attribution, confirmer, and timestamp for an exact SourceAsset or MediaAsset. Unknown or unresolved uploaded scene media is rejected from the plan. Rendered assets are private, owner-scoped, and never return a local path or storage key. `MediaReviewDecision` is an append-only decision for an exact primary asset hash; re-rendering creates a new decision target. Media approval covers layout, legibility, timing, and media quality for workflow use and does not certify factual claims. Evidence review remains separate.

The CI backend job installs and verifies FFmpeg/ffprobe, executes deterministic rendering/audio/timing/retry tests, creates a fixture infographic, silent MP4, VTT captions, renderer plan, provenance, byte/hash metrics, and an unchecked human-review checklist, then uploads that bundle as a 14-day artifact. Human visual/audio quality remains pending until a person reviews the files.

## Source revision, update, and export

```text
SourcePackVersion V1 / SourceVersion V1
  -> append immutable SourcePackVersion V2 / SourceVersion V2
  -> deterministic SourceRegion alignment + validated block dependencies
  -> affected / needs-review / unknown impact per artifact block
  -> server-authorized block replacements + exact preservation of other blocks
  -> new draft ArtifactVersion linked to V2, or full regeneration from V2
```

Exact content uniquely aligned across versions may be unchanged or moved. Changed and removed dependency regions affect their linked blocks; duplicate, split, and merged matches require review, and additions keep artifact impact unknown where the new material may matter. Legacy segment diffs remain display information. Missing or unresolved dependencies do not authorize targeted editing. A completed claim scan with no mapped material claims can mark non-claim blocks unaffected; unresolved claim coverage or mappings remain unknown.

The transformation's current source pointer moves to V2; V1 and existing artifact versions remain intact. Targeted updates preserve the prior artifact as input but identify V2 as authoritative. Copy and Markdown download format structured artifacts as readable content projections and preserve plain text families as text. Infographic and Video Package keep their editable specs and readable text while providing private SVG/PNG or MP4/VTT downloads for the selected exact artifact version. Editable PowerPoint export maps each validated `PresentationSpec` slide to editable text and shape objects with matching speaker notes using PptxGenJS; it does not generate imagery.

## Persistence and deployment boundary

FastAPI, SQLAlchemy, and Alembic form a small modular monolith; SQLite is the local/demo database. The React/Vite frontend calls the authenticated API through the development proxy. The repository does not claim production hardening, connected cloud-drive ingestion, or automatic fact validation. Exact quotation matching establishes that a quote occurs in a stored source, not that a claim is complete or true.
