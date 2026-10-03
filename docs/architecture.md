# AxiomWeave architecture

## Identity and request boundary

```text
Username + password -> Argon2id verification -> local user
  -> HttpOnly session cookie -> owner-scoped React workspace
```

The backend verifies passwords with Argon2id, maps the normalized username to a local user, and issues a separate eight-hour application session. Only a SHA-256 digest of the random session token is stored. The cookie is HttpOnly, SameSite=Lax, and Secure outside development. Login failures use a generic response and a persistent username-keyed throttle. Logout revokes the session. User IDs come from the authenticated session, never request JSON. Password authentication is not phishing-resistant and is the selected Tier-A demo method. Source text and supporting context are treated as untrusted data.

## Source, brief, and generated artifacts

```text
Paste / TXT / MD / DOCX / PDF / one public URL
  -> for URLs: safe bounded HTTP fetch -> HTML/main-content extraction
  -> text or DOCX extraction; PDF native text extraction page by page
  -> OCR/Vision fallback only for PDF pages with under 40 usable native characters
  -> owner-scoped SourcePack -> immutable SourcePackVersion
  -> immutable source memberships (PRIMARY / SUPPORTING / STYLE / REFERENCE / OPERATOR_CONTEXT)
  -> exact SourceVersion + SourceAsset -> addressable SourceRegions
  -> compatibility SourceVersion + SHA-256 + SourceSegments
  -> TransformationRun (separate context and communication controls)
  -> ArtifactRun per selected format -> immutable ArtifactVersion history
```

All seven output types are executable: executive summary, LinkedIn post, X Post, formal advisory, presentation, infographic, and video package. Each selected family receives an independent durable Job and ContextManifest, so failures and retries remain isolated. X Post currently uses the compatible single-post contract, limited to 220 provider output tokens and 280 Unicode code points. A centralized server-owned contract defines each family's schema version, prompt metadata, token budget, validation, serialization, and readable text projection. New versions store their artifact schema version; historical rows remain nullable rather than receiving invented metadata. Existing text families stay plain text, and Presentation keeps its established `PresentationSpec` JSON shape. Infographic creates an editable bounded `InfographicSpec`; Video Package creates an editable bounded `VideoPackageSpec` with ordered scenes. Neither spec produces rendered media in Phase 3.

URL imports accept one public HTTP/HTTPS page at a time. The fetcher validates DNS results and pins the connection to a validated public IP, manually revalidates up to three redirects, streams at most 2 MiB, and extracts readable HTML or plain text. File and URL imports create a SourcePackVersion when extraction succeeds; the composer reuses that owned version when saving the transformation. Pasted text creates its SourcePackVersion when the transformation is saved. If an imported source is edited in the composer, the app appends a new version and keeps the imported version intact. URL assets retain the validated final URL as provenance and do not fabricate a binary object. The importer does not crawl or execute page scripts.

## OpenAI generation boundary

```text
FastAPI generation / analysis routes -> provider protocol -> OpenAI Responses API
```

The server owns model choice and API key. Primary artifact generation and targeted updates use `gpt-6-luna`; evidence proposals, discrepancy analysis, and scanned-page OCR use the utility model (`SIH_OPENAI_UTILITY_MODEL`, default `gpt-5-nano`). Generation and analysis calls have code-owned output-token limits. Primary and utility structured generation uses low reasoning effort; OCR uses a separate bounded transcription call. All Responses API requests set `store=False`. Structured responses use the exact server-owned Pydantic model for Presentation, Infographic, and Video Package, plus the existing evidence and discrepancy schemas. Incomplete provider responses fail without persisting a successful artifact version. Provider errors are converted to safe API errors; raw provider output and credentials are not returned as diagnostics.

Document uploads are bounded: text is capped at 80 KiB; DOCX and PDF at 8 MiB; PDFs at 20 pages; OCR fallback at 8 pages; normalized extracted text at 20,000 characters. PDF text retains `# Page N` markers and its regions retain page locators. Encrypted, corrupt, and empty PDFs are rejected. Original uploads are stored under server-generated keys in the private local directory configured by `SIH_PRIVATE_ASSET_DIR`; that directory is not served by FastAPI. Rendered OCR images are temporary. If the database transaction fails, the app attempts to delete the prepared file; a filesystem failure during that cleanup can leave an unreferenced private file for manual cleanup. The storage boundary is local-development only; no production object-store adapter is deployed.

Each pack snapshot has one `PRIMARY` member; an ordered membership row names the exact source version and asset assigned to that snapshot. Additional sources may be `SUPPORTING`, `STYLE`, `REFERENCE`, or `OPERATOR_CONTEXT`. The server validates the role, source/asset pairing, and common owner before writing memberships. The deterministic role policy permits PRIMARY to ground facts; SUPPORTING can ground or contextualize, but conflicts with PRIMARY require review rather than silent override; STYLE controls presentation only; REFERENCE is non-factual by default; OPERATOR_CONTEXT controls the task, not source truth. This policy does not implement semantic conflict detection or resolution.

The additive Phase 1B migrations backfill each existing `Source`, `SourceVersion`, and `SourceSegment` into a SourcePack, SourcePackVersion, text SourceAsset, SourceRegion, and one `PRIMARY` membership linking the exact legacy version and asset. Historical raw uploads are not reconstructed. New source writes go through one snapshot writer that creates the pack records, membership snapshot, and required legacy projection in the same database transaction. A revision appends a pack version and carries forward non-primary members unless its server caller explicitly supplies a replacement membership set. Existing generation, evidence, and revision code continues to read the legacy projection. The old asset-level authority column remains only for migration compatibility; membership roles are canonical.

## Phase 2 context, claims, and retrieval

Each newly queued generation Job receives an immutable `ContextManifest` in the same transaction. The manifest records its exact SourcePackVersion and SourceVersion, route/profile versions, query-construction and budget-policy versions, estimate, reserved margin, extraction coverage, warnings, and region-level entries with role, locator, and content hash. Database triggers protect manifests and entries against direct SQL updates or deletes. The worker validates and renders those stored entries; it does not rerun retrieval. The resulting `ArtifactVersion` points to the same manifest. Historical jobs and artifact versions remain nullable because no historical selection is fabricated.

R0 is the generation baseline. The versioned `context-chars-v1` policy estimates Unicode code points, admits all eligible PRIMARY and SUPPORTING regions up to a 20,000-character context budget, and reserves 5,000 units for output/schema/evidence overhead. The estimate is not provider tokenization. Ordinary single-source R0 preserves the full legacy primary source text. Supporting regions carry role, source identity/version, and locator labels. Partial extraction remains visible. If R0 exceeds its bound and no profile is admitted, the manifest requires review; content is not silently truncated.

Material-claim scans split immutable artifact communication text into deterministic bounded batches. For structured families, the exact deterministic human-readable projection is stored with the scan and scanned instead of raw JSON syntax. Successful batches persist independently and retries process only incomplete batches. Scan status and UI coverage come from total/completed/failed/needs-review batches, with no global claim-count cap. `KnowledgeAssertion` rows are candidate propositions tied to exact regions and exact quote spans when available. Provenance validation does not establish entailment, completeness, or truth; invalid spans remain unresolved and require review. `KnowledgeRelation` is storage only and is not traversed during generation.

The PostgreSQL retrieval repository filters by owner, exact SourcePackVersion, membership role, source-version pairing, asset extraction state, and exact SourceRegion. PostgreSQL native FTS uses the language-neutral `simple` configuration and is not described as BM25. The predeclared four-pack/six-task fixture measured top-2 FTS recall of 2/7 required regions and 1/4 qualifiers, with four task misses. FTS used 117 of R0's 785 source-region characters, an 85.1% reduction, and remains an unpromoted candidate. Character counts cover original region text only; they exclude role labels and provider schema overhead. Exact pgvector and fixed RRF verify ranking and manifest mechanics only; without an approved semantic embedding profile, vector/hybrid quality is not evaluated. Full fixture metrics and limitations are in `backend/evals/retrieval/README.md`.

## Review, evidence, and discrepancies

Review APIs return owner-scoped artifact versions and provenance. Every family can be edited through family validation, and edits append an immutable version carrying the family schema version and ContextManifest lineage. Evidence analysis proposes claim/quote pairs; deterministic application code checks each quote against the exact source version and records a source segment locator only for a verified match. Unlocated proposals remain explicitly unsupported. Discrepancy analysis compares sibling outputs from one transformation using readable projections and stores possible conflicts as review findings. Dismissal updates the finding's review status without rewriting artifacts.

## Source revision, update, and export

```text
SourcePackVersion V1 / SourceVersion V1
  -> append immutable SourcePackVersion V2 / SourceVersion V2
  -> deterministic segment diff + evidence impact
   -> targeted update (prior artifact + V1 + changed material + authoritative V2)
   -> new ArtifactVersion linked to V2, or full regeneration from V2
```

The transformation's current source pointer moves to V2; V1 and existing artifact versions remain intact. Targeted updates preserve the prior artifact as input but identify V2 as authoritative. Copy and Markdown download format structured artifacts as readable content projections and preserve plain text families as text. Infographic and Video Package exports are content/specification only; PNG/SVG/PDF rendering and MP4/audio production remain Phase 5 work. Editable PowerPoint export maps each validated `PresentationSpec` slide to editable text and shape objects with matching speaker notes using PptxGenJS; it does not generate imagery.

## Persistence and deployment boundary

FastAPI, SQLAlchemy, and Alembic form a small modular monolith; SQLite is the local/demo database. The React/Vite frontend calls the authenticated API through the development proxy. The repository does not claim production hardening, connected cloud-drive ingestion, or automatic fact validation. Exact quotation matching establishes that a quote occurs in a stored source, not that a claim is complete or true.
