# SIH26154 architecture

## Implemented request path

```text
Browser -> Google Identity Services -> POST /api/auth/google
       -> AxiomWeave local session cookie -> React/Vite -> FastAPI
                                                   |-> GET /api/health (public)
                                                   |-> GET /api/auth/session
                                                   |-> POST /api/auth/logout
                                                   |-> POST /api/sources/text-file (authenticated)
                                                   `-> POST /api/transformations/prepare (authenticated)
```

Google Identity Services returns an ID token to the browser callback. The browser sends the credential to the backend, which verifies the signature and audience against `SIH_GOOGLE_CLIENT_ID`, then identifies the local account by the stable Google `sub`. The backend issues a separate random application-session token, persists only its SHA-256 digest, and returns it in an HttpOnly, SameSite=Lax cookie. The cookie is Secure outside development and expires after eight hours. Logout revokes the session and clears its cookie. No Google access token, refresh token, client secret, or Drive scope is used.

Health remains public. Text-file extraction and transformation request preparation require an application session. Pasted or extracted source is validated and returned as a request ready for a later stage; it is not persisted or generated through these routes. Source text and supporting context remain untrusted input.

## Persistence foundation

The backend defines SQLAlchemy 2 models and an Alembic migration for `User`, `AuthSession`, `Source`, `SourceVersion`, `SourceSegment`, `TransformationRun`, `ArtifactRun`, and `ArtifactVersion`. The default database is SQLite, configured through `SIH_DATABASE_URL`. SQLite connections enable foreign-key enforcement. Source and artifact version number uniqueness constraints allow distinct historical versions while preventing duplicate version numbers for the same parent.

Saved-source and artifact records are not connected to user-facing API routes. Explicit owner-scoped selectors constrain queries for Source, SourceVersion, TransformationRun, ArtifactRun, and ArtifactVersion by their owning user. These establish the query boundary for future endpoints but do not imply that those APIs exist. Saved-source workflows, user-facing generation, review/history, source evidence, discrepancy warnings, source revision, and export are not implemented.

## Generation boundary

The backend defines an internal generation request/result contract and provider protocol, plus internal Executive Summary generation logic that builds artifact instructions and returns a draft through that boundary. No live model provider, generation API, user-facing generated artifact, or artifact persistence workflow is implemented.

## Stable boundaries

- Source content and supporting context are untrusted data and do not carry application authority.
- Any model interaction remains controlled by the application.
- The frontend communicates with backend capabilities through the HTTP API.
- The system remains a small modular monolith unless implemented needs demonstrate otherwise.
- Schema ownership fields prepare for later access checks; they do not enforce owner isolation by themselves.
- Source and artifact version rows are modeled as immutable history by application contract; structural persistence does not certify content truth.
