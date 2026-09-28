# SIH26154 architecture

## Implemented request path

```text
Browser → React/Vite frontend → HTTP API → FastAPI
                                      ├→ GET /api/health
                                      ├→ POST /api/sources/text-file
                                      └→ POST /api/transformations/prepare
```

The browser submits pasted text or uses the stateless text-file extraction endpoint to populate the same canonical source text. The backend validates and returns the canonical request as ready for a later stage. No artifact content is generated through the API.

## Persistence foundation

The backend defines SQLAlchemy 2 models and an Alembic migration for `User`, `AuthSession`, `Source`, `SourceVersion`, `SourceSegment`, `TransformationRun`, `ArtifactRun`, and `ArtifactVersion`. The default database is SQLite, configured through `SIH_DATABASE_URL`. SQLite connections enable foreign-key enforcement. Source and artifact version number uniqueness constraints allow distinct historical versions while preventing duplicate version numbers for the same parent.

These records are not connected to API routes. Google authentication, session issuance, owner-scoped API access, saved-source workflows, user-facing generation, review/history, source evidence, discrepancy warnings, source revision, and export are not implemented. Owner fields in the schema are not API access control.

## Generation boundary

The backend defines an internal generation request/result contract and provider protocol, plus internal Executive Summary generation logic that builds artifact instructions and returns a draft through that boundary. No live model provider, generation API, user-facing generated artifact, or artifact persistence workflow is implemented.

## Stable boundaries

- Source content and supporting context are untrusted data and do not carry application authority.
- Any model interaction remains controlled by the application.
- The frontend communicates with backend capabilities through the HTTP API.
- The system remains a small modular monolith unless implemented needs demonstrate otherwise.
- Schema ownership fields prepare for later access checks; they do not enforce owner isolation by themselves.
- Source and artifact version rows are modeled as immutable history by application contract; structural persistence does not certify content truth.
