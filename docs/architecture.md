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

The five Tier-A output types are executive summary, LinkedIn post, X Post, formal advisory, and presentation with speaker notes. X Post output is limited to 220 provider output tokens and validated at 280 Unicode code points before persistence. Each output has an independent run state, allowing partial failure and retry. Version history records its source version, provider/model, prompt version/hash, and review status. Human edits create another version. Presentation content is validated structured data and is rendered with React text nodes for review.

URL imports accept one public HTTP/HTTPS page at a time. The fetcher validates DNS results and pins the connection to a validated public IP, manually revalidates up to three redirects, streams at most 2 MiB, and extracts readable HTML or plain text. File and URL imports create a SourcePackVersion when extraction succeeds; the composer reuses that owned version when saving the transformation. Pasted text creates its SourcePackVersion when the transformation is saved. If an imported source is edited in the composer, the app appends a new version and keeps the imported version intact. URL assets retain the validated final URL as provenance and do not fabricate a binary object. The importer does not crawl or execute page scripts.

## OpenAI generation boundary

```text
FastAPI generation / analysis routes -> provider protocol -> OpenAI Responses API
```

The server owns model choice and API key. Primary artifact generation and targeted updates use `gpt-6-luna`; evidence proposals, discrepancy analysis, and scanned-page OCR use the utility model (`SIH_OPENAI_UTILITY_MODEL`, default `gpt-5-nano`). Generation and analysis calls have code-owned output-token limits. Primary and utility structured generation uses low reasoning effort; OCR uses a separate bounded transcription call. All Responses API requests set `store=False`. Structured responses are used for presentation specifications, evidence proposals, discrepancy findings, and targeted updates. Incomplete provider responses fail without persisting a successful artifact version. Provider errors are converted to safe API errors; raw provider output and credentials are not returned as diagnostics.

Document uploads are bounded: text is capped at 80 KiB; DOCX and PDF at 8 MiB; PDFs at 20 pages; OCR fallback at 8 pages; normalized extracted text at 20,000 characters. PDF text retains `# Page N` markers and its regions retain page locators. Encrypted, corrupt, and empty PDFs are rejected. Original uploads are stored under server-generated keys in the private local directory configured by `SIH_PRIVATE_ASSET_DIR`; that directory is not served by FastAPI. Rendered OCR images are temporary. If the database transaction fails, the app attempts to delete the prepared file; a filesystem failure during that cleanup can leave an unreferenced private file for manual cleanup. The storage boundary is local-development only; no production object-store adapter is deployed.

Each pack snapshot has one `PRIMARY` member; an ordered membership row names the exact source version and asset assigned to that snapshot. Additional sources may be `SUPPORTING`, `STYLE`, `REFERENCE`, or `OPERATOR_CONTEXT`. The server validates the role, source/asset pairing, and common owner before writing memberships. The deterministic role policy permits PRIMARY to ground facts; SUPPORTING can ground or contextualize, but conflicts with PRIMARY require review rather than silent override; STYLE controls presentation only; REFERENCE is non-factual by default; OPERATOR_CONTEXT controls the task, not source truth. This policy does not implement semantic conflict detection or resolution.

The additive Phase 1B migrations backfill each existing `Source`, `SourceVersion`, and `SourceSegment` into a SourcePack, SourcePackVersion, text SourceAsset, SourceRegion, and one `PRIMARY` membership linking the exact legacy version and asset. Historical raw uploads are not reconstructed. New source writes go through one snapshot writer that creates the pack records, membership snapshot, and required legacy projection in the same database transaction. A revision appends a pack version and carries forward non-primary members unless its server caller explicitly supplies a replacement membership set. Existing generation, evidence, and revision code continues to read the legacy projection. The old asset-level authority column remains only for migration compatibility; membership roles are canonical.

## Review, evidence, and discrepancies

Review APIs return owner-scoped artifact versions and provenance. Evidence analysis proposes claim/quote pairs; deterministic application code checks each quote against the exact source version and records a source segment locator only for a verified match. Unlocated proposals remain explicitly unsupported. Discrepancy analysis compares sibling outputs from one transformation and stores possible conflicts as review findings. Dismissal updates the finding's review status without rewriting artifacts.

## Source revision, update, and export

```text
SourcePackVersion V1 / SourceVersion V1
  -> append immutable SourcePackVersion V2 / SourceVersion V2
  -> deterministic segment diff + evidence impact
   -> targeted update (prior artifact + V1 + changed material + authoritative V2)
   -> new ArtifactVersion linked to V2, or full regeneration from V2
```

The transformation's current source pointer moves to V2; V1 and existing artifact versions remain intact. Targeted updates preserve the prior artifact as input but identify V2 as authoritative. Copy and Markdown download format presentations as readable slide sections and preserve regular artifacts as text. Editable PowerPoint export maps each validated `PresentationSpec` slide to editable text and shape objects with matching speaker notes using PptxGenJS; it does not generate imagery.

## Persistence and deployment boundary

FastAPI, SQLAlchemy, and Alembic form a small modular monolith; SQLite is the local/demo database. The React/Vite frontend calls the authenticated API through the development proxy. The repository does not claim production hardening, connected cloud-drive ingestion, or automatic fact validation. Exact quotation matching establishes that a quote occurs in a stored source, not that a claim is complete or true.
