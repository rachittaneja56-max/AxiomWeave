# AxiomWeave architecture

## Identity and request boundary

```text
Username + password -> Argon2id verification -> local user
  -> HttpOnly session cookie -> owner-scoped React workspace
```

The backend verifies passwords with Argon2id, maps the normalized username to a local user, and issues a separate eight-hour application session. Only a SHA-256 digest of the random session token is stored. The cookie is HttpOnly, SameSite=Lax, and Secure outside development. Login failures use a generic response and a persistent username-keyed throttle. Logout revokes the session. User IDs come from the authenticated session, never request JSON. Password authentication is not phishing-resistant and is the selected Tier-A demo method. Source text and supporting context are treated as untrusted data.

## Source, brief, and generated artifacts

```text
Paste / UTF-8 TXT or MD
  -> normalized Source -> immutable SourceVersion + SHA-256 + SourceSegments
  -> TransformationRun (separate context and communication controls)
  -> ArtifactRun per selected format -> immutable ArtifactVersion history
```

The four Tier-A output types are executive summary, LinkedIn post, formal advisory, and presentation with speaker notes. Each output has an independent run state, allowing partial failure and retry. Version history records its source version, provider/model, prompt version/hash, and review status. Human edits create another version. Presentation content is validated structured data and is rendered with React text nodes.

## OpenAI generation boundary

```text
FastAPI generation / analysis routes -> provider protocol -> OpenAI Responses API
```

The server owns the model choice and API key. The pinned model is `gpt-6-luna`; requests use low reasoning effort and `store=False`. Structured responses are used for presentation specifications, evidence proposals, discrepancy findings, and targeted updates. Provider errors are converted to safe API errors; raw provider output and credentials are not returned as diagnostics.

## Review, evidence, and discrepancies

Review APIs return owner-scoped artifact versions and provenance. Evidence analysis proposes claim/quote pairs; deterministic application code checks each quote against the exact source version and records a source segment locator only for a verified match. Unlocated proposals remain explicitly unsupported. Discrepancy analysis compares sibling outputs from one transformation and stores possible conflicts as review findings. Dismissal updates the finding's review status without rewriting artifacts.

## Source revision, update, and export

```text
V1 -> save immutable V2 -> deterministic segment diff + evidence impact
   -> targeted update (prior artifact + V1 + changed material + authoritative V2)
   -> new ArtifactVersion linked to V2, or full regeneration from V2
```

The transformation's current source pointer moves to V2; V1 and existing artifact versions remain intact. Targeted updates preserve the prior artifact as input but identify V2 as authoritative. Copy and Markdown download format presentations as readable slide sections and preserve regular artifacts as text.

## Persistence and deployment boundary

FastAPI, SQLAlchemy, and Alembic form a small modular monolith; SQLite is the local/demo database. The React/Vite frontend calls the authenticated API through the development proxy. The repository does not claim production hardening, connected cloud-drive ingestion, or automatic fact validation. Exact quotation matching establishes that a quote occurs in a stored source, not that a claim is complete or true.
