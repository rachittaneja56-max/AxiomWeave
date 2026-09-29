# AxiomWeave architecture

## Identity and request boundary

```text
Username + password -> Argon2id verification -> local user
  -> HttpOnly session cookie -> owner-scoped React workspace
```

The backend verifies passwords with Argon2id, maps the normalized username to a local user, and issues a separate eight-hour application session. Only a SHA-256 digest of the random session token is stored. The cookie is HttpOnly, SameSite=Lax, and Secure outside development. Login failures use a generic response and a persistent username-keyed throttle. Logout revokes the session. User IDs come from the authenticated session, never request JSON. Password authentication is not phishing-resistant and is the selected Tier-A demo method. Source text and supporting context are treated as untrusted data.

## Source, brief, and generated artifacts

```text
Paste / TXT / MD / DOCX / PDF
  -> text or DOCX extraction; PDF native text extraction page by page
  -> OCR/Vision fallback only for PDF pages with under 40 usable native characters
  -> normalized Source -> immutable SourceVersion + SHA-256 + SourceSegments
  -> TransformationRun (separate context and communication controls)
  -> ArtifactRun per selected format -> immutable ArtifactVersion history
```

The four Tier-A output types are executive summary, LinkedIn post, formal advisory, and presentation with speaker notes. Each output has an independent run state, allowing partial failure and retry. Version history records its source version, provider/model, prompt version/hash, and review status. Human edits create another version. Presentation content is validated structured data and is rendered with React text nodes for review.

## OpenAI generation boundary

```text
FastAPI generation / analysis routes -> provider protocol -> OpenAI Responses API
```

The server owns model choice and API key. Primary artifact generation and targeted updates use `gpt-6-luna`; evidence proposals, discrepancy analysis, and scanned-page OCR use the utility model (`SIH_OPENAI_UTILITY_MODEL`, default `gpt-5-nano`). Generation and analysis calls have code-owned output-token limits. Primary and utility structured generation uses low reasoning effort; OCR uses a separate bounded transcription call. All Responses API requests set `store=False`. Structured responses are used for presentation specifications, evidence proposals, discrepancy findings, and targeted updates. Incomplete provider responses fail without persisting a successful artifact version. Provider errors are converted to safe API errors; raw provider output and credentials are not returned as diagnostics.

Document uploads are bounded: text is capped at 80 KiB; DOCX and PDF at 8 MiB; PDFs at 20 pages; OCR fallback at 8 pages; normalized extracted text at 20,000 characters. PDF text retains `# Page N` markers. Encrypted, corrupt, and empty PDFs are rejected. Raw uploads and rendered OCR images are not persisted.

## Review, evidence, and discrepancies

Review APIs return owner-scoped artifact versions and provenance. Evidence analysis proposes claim/quote pairs; deterministic application code checks each quote against the exact source version and records a source segment locator only for a verified match. Unlocated proposals remain explicitly unsupported. Discrepancy analysis compares sibling outputs from one transformation and stores possible conflicts as review findings. Dismissal updates the finding's review status without rewriting artifacts.

## Source revision, update, and export

```text
V1 -> save immutable V2 -> deterministic segment diff + evidence impact
   -> targeted update (prior artifact + V1 + changed material + authoritative V2)
   -> new ArtifactVersion linked to V2, or full regeneration from V2
```

The transformation's current source pointer moves to V2; V1 and existing artifact versions remain intact. Targeted updates preserve the prior artifact as input but identify V2 as authoritative. Copy and Markdown download format presentations as readable slide sections and preserve regular artifacts as text. Editable PowerPoint export maps each validated `PresentationSpec` slide to editable text and shape objects with matching speaker notes using PptxGenJS; it does not generate imagery.

## Persistence and deployment boundary

FastAPI, SQLAlchemy, and Alembic form a small modular monolith; SQLite is the local/demo database. The React/Vite frontend calls the authenticated API through the development proxy. The repository does not claim production hardening, connected cloud-drive ingestion, or automatic fact validation. Exact quotation matching establishes that a quote occurs in a stored source, not that a claim is complete or true.
