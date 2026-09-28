# SIH26154 architecture

## Authenticated transformation save

```text
Browser -> Google Identity Services -> POST /api/auth/google
       -> AxiomWeave local session cookie -> authenticated React workspace
       -> POST /api/transformations
       -> canonical source normalization
       -> Source -> SourceVersion -> SourceSegments
       -> TransformationRun (supporting context and controls)
```

Google Identity Services returns an ID token to the browser callback. The backend verifies the token signature and audience against `SIH_GOOGLE_CLIENT_ID`, then identifies the local account by the stable Google `sub`. It issues a separate random application-session token in an HttpOnly, SameSite=Lax cookie and stores only its SHA-256 digest. Logout revokes the local session. Health remains public; source extraction, request preparation, and transformation saving require a valid local session.

The save route derives ownership from the authenticated user, normalizes the source, creates a `Source`, its first immutable `SourceVersion`, deterministic segments, and one `TransformationRun` in one database transaction. Supporting context remains on the run and is not included in the source text, hash, or segments. The persisted outputs are the four Tier-A choices. The response reports saved record identifiers and version metadata without echoing source, context, or identity details.

Canonical text normalization removes a leading Unicode BOM and changes CRLF/CR to LF. Other characters are preserved. Empty or whitespace-only text and content over 20,000 characters are rejected without truncation. UTF-8 TXT/MD extraction uses the same normalization after decoding. Source segmentation groups adjacent non-heading lines into paragraphs, splits at blank lines, and stores Markdown headings as their own segments with deterministic locators.

## Persistence and generation boundary

The SQLAlchemy schema and current Alembic migration include `User`, `AuthSession`, `Source`, `SourceVersion`, `SourceSegment`, `TransformationRun`, `ArtifactRun`, and `ArtifactVersion`. The save workflow writes source and transformation records only. It does not create artifact runs or generated content. No new migration was required for this slice.

The backend defines an internal generation request/result contract, provider protocol, and Executive Summary logic. No live provider or user-facing generation API is connected to the transformation-save action. The following remain unimplemented: dashboard, source reuse, artifact review/history, evidence links, discrepancy warnings, source revision UI/diff/impact, targeted updates, and export. Source segments provide stable source structure but are not evidence links.

## Stable boundaries

- Source content and supporting context are untrusted data and carry no application authority.
- Owner IDs come from the authenticated local user, never request JSON.
- SourceVersion hashes identify exact stored source text; they do not prove authenticity, correctness, or semantic equivalence.
- Any future model interaction remains controlled by the application.
- The system remains a small modular monolith unless implemented needs demonstrate otherwise.
