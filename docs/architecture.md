# Architecture

## Application shape

```text
React/Vite workspace
        │ authenticated /api requests
FastAPI routes ── typed commands ── SQLAlchemy
        │                              │
        ├── private asset storage      └── SQLite or PostgreSQL
        └── durable jobs ── model_io and media_cpu workers
```

The backend is a modular monolith. API routes handle HTTP schemas, authentication, and transport errors. Typed application commands validate writes and dispatch them to the relevant application code. Artifact generation and media rendering use separate workers so model calls and CPU-heavy rendering do not block requests.

## Identity and access

Passwords are hashed with Argon2id. Successful sign-in issues a random eight-hour session token; the database stores only its SHA-256 digest. The cookie is HttpOnly, SameSite=Lax, and Secure outside development. Login failures are throttled, and rate limits are stored in the database. Mutating endpoints derive the owner from the authenticated session. Source and rendered-media previews use owner-scoped routes over a private local storage boundary.

## Sources and generation

```text
Paste / TXT / MD / DOCX / PDF / media / one public URL
  -> bounded validation and extraction
  -> SourcePack and immutable SourcePackVersion
  -> role-labeled source versions and addressable SourceRegions
  -> TransformationRun and communication brief
  -> one ArtifactRun and durable Job per selected family
  -> immutable ArtifactVersions with a ContextManifest
```

Each SourcePackVersion records exact source versions and assets with roles such as `PRIMARY`, `SUPPORTING`, `STYLE`, `REFERENCE`, and `OPERATOR_CONTEXT`. The role policy controls how each member may affect factual content. Source revisions append versions; prior versions remain available.

Every new generation job stores an immutable `ContextManifest` in the same transaction. It identifies the exact source-pack version, selected regions, role, locator, content hash, extraction coverage, and context policy. Workers render the saved manifest rather than selecting context again. The current R0 policy includes eligible `PRIMARY` and `SUPPORTING` regions within a 20,000-character context bound and requires review when the source exceeds that bound. Historical records remain nullable where their original selection was never recorded.

The seven output families are executive summary, LinkedIn post, X post, formal advisory, presentation, infographic, and video package. Each family has a server-owned versioned contract. Jobs have independent state, retries, and version history. Structured families store editable specifications alongside readable content projections.

## Model and evidence boundaries

The server selects models through a task-profile resolver. Defaults are `gpt-6-luna` for artifact generation and analysis and `gpt-5-nano` for scanned-page OCR; configuration can override task profiles. API callers cannot choose providers or models. OpenAI Responses API storage is disabled with `store=False`; provider retention follows applicable provider terms.

Material claims are split into bounded, resumable scans. Model-suggested source IDs and quotations are proposals until checked against the exact selected manifest, role, region, and text span. Quote location establishes that text occurs in a source; it does not establish that a claim is true, complete, or supported. Evidence assessments and discrepancy findings are review prompts, with human decisions stored separately.

For a source revision, exact source-region alignment and validated artifact-block dependencies determine potential impact. Ambiguous or incomplete lineage requires review. Selective updates accept only server-authorized replacements and create a new draft version; accepted versions remain immutable.

## ActionPlans and command execution

The planner receives a bounded summary of the authenticated user's workspace and server-owned command schemas. It returns a proposal, not an execution request. The application validates every proposed command against current ownership, state, and policy, then hashes the relevant preconditions. Consequential plans require explicit confirmation. Confirmation rechecks the plan hash and workspace state before dispatch through the same typed command handlers used by manual operations. Plans cannot invoke arbitrary tools, SQL, or providers.

## Media processing

Infographics and video packages retain editable, immutable specifications. Deterministic renderers produce private SVG/PNG assets and MP4/WebVTT output for an exact artifact version. Media rendering runs through dependent `media_cpu` jobs; failed scene jobs can be retried independently. FFmpeg receives a local argument array with shell execution disabled, bounded timeouts, and generated filenames. FFprobe checks output streams, dimensions, frame rate, and duration.

Original source images, audio, and video are retained as private assets with extraction coverage and region locators. No live Vision, ASR, TTS, image-generation, or video-generation provider is configured. External scene media requires eligible rights and applicable consent before composition. Media review covers layout and playback quality; factual review remains separate.

## Persistence and limits

SQLite is the local default. PostgreSQL migrations, constraints, job claims, and runtime persistence are exercised by integration tests. Source uploads and rendered assets use the private directory configured by `SIH_PRIVATE_ASSET_DIR`; production object storage is not implemented. Production-scale queue concurrency has not been demonstrated. Import, extraction, prompt, context, and media limits are enforced in code to bound resource use.
