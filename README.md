# AxiomWeave — SIH26154

**Source-Grounded Content Transformation Workspace**

One source. Many artifacts. Every claim traceable.

## Problem and solution

Teams often rewrite the same authoritative material for several audiences and formats. Manual reuse can introduce drift, hide unsupported claims, and make later source corrections hard to apply. AxiomWeave is a source-grounded content transformation workspace for saving a source and communication brief once, generating seven related artifact families independently, and reviewing each version with its source provenance visible.

## Tier-A workflow

- Username/password sign-in and an owner-scoped transformation dashboard.
- Paste source text, upload `.txt`, `.md`, `.docx`, or `.pdf`, or import one public HTTP/HTTPS article URL; keep supporting context separate. DOCX paragraphs, headings, and tables are extracted. PDFs use native text extraction first; scanned pages use OCR/Vision only when native text is unavailable. URL import reads one public page without login, JavaScript rendering, or crawling.
- Set audience, tone, language, detail, objective, and style.
- Generate Executive Summary, Professional / LinkedIn Post, X Post, Formal Advisory, Presentation, Infographic, and Video Package artifacts. Each selected family runs as its own durable Job with independent failure, retry, regeneration, and version history. X Post currently uses the single-post contract, capped at 280 Unicode code points.
- Infographic and Video Package keep editable, immutable specs and render finished private SVG/PNG or MP4/VTT derivatives for the exact selected artifact version. Deterministic scene cards and captions work without an image/video-generation or TTS provider; absent narration audio, the MP4 contains silence.
- Bounded PNG/JPEG, WAV/MP3/M4A, and MP4 source uploads retain their original bytes privately, with explicit extraction coverage and image/audio/video region locators. No live Vision or ASR provider is selected; unavailable extraction stays visible and is not treated as factual evidence.
- External scene images and narration audio remain excluded until the owner records an eligible rights basis and applicable consent. Media review covers layout, legibility, timing, and media quality; factual evidence review stays separate.
- Review and edit immutable artifact versions; accept or reject drafts.
- Inspect exact source quotations and unsupported claims. Compare sibling outputs for possible discrepancies, then dismiss a finding without changing artifact text.
- Save source V2, inspect a deterministic paragraph diff and potentially affected evidence, run a targeted update, or regenerate fully from V2.
- Copy artifact text or download readable Markdown. Presentations also export as editable PowerPoint slides with speaker notes. Structured families export their readable content specification.
- Each family Job uses its own immutable ContextManifest. Sources that fit the budget use R0 full context; PostgreSQL FTS remains an inspectable candidate path and is not the default.
- Scan material claims in bounded, resumable batches with visible coverage. Candidate assertions retain exact source provenance and stay marked for review.

## Architecture

The application is a React/Vite frontend and a FastAPI/SQLAlchemy modular monolith backed by SQLite for local use. Artifact generation and media rendering use durable database Jobs with separate `model_io` and `media_cpu` worker processes, one claimed job per process at a time. Job attempts, dependency edges, leases, and terminal state are stored in the database. SQLite supports local demo use; production-scale queue concurrency has not been demonstrated. Source uploads and rendered media use the owner-scoped private local directory configured by `SIH_PRIVATE_ASSET_DIR`; production object storage is not implemented. Image/audio/video extraction interfaces are bounded and retain exact source regions and coverage; no live Vision or ASR provider is selected. The seven output families use server-owned versioned contracts. Claim scanning and discrepancy analysis use deterministic human-readable projections for structured artifacts. `docs/architecture.md` gives the data and request flow.

Phase 5 operational limits: source images 10 MiB, audio 16 MiB / 60 seconds, and MP4 video 100 MiB / 180 seconds (sampled at five-second intervals, up to 36 frames). Scene uploads use 10 MiB images capped at 4,000 pixels per edge and 16 megapixels, or 16 MiB audio capped at 60 seconds. Rendered MP4 output is capped at 256 MiB / 180 seconds and uses 1280×720 at 30 fps. These are resource bounds, not quality thresholds. Local media workers and the fixture generator require FFmpeg and ffprobe on `PATH`; run them with `uv run python -m app.job_worker --resource-class media_cpu` and `uv run python scripts/create_phase5_bundle.py --output-dir .phase5-human-review` from `backend`.

Model routing comes from a server-owned task profile resolver. Artifact generation, lineage, evidence analysis, consistency analysis, and ActionPlan planning use `gpt-6-luna` by default; scanned-page OCR uses `gpt-5-nano`. `SIH_OPENAI_ACTION_MODEL`, `SIH_OPENAI_EVIDENCE_MODEL`, `SIH_OPENAI_CONSISTENCY_MODEL`, and `SIH_OPENAI_OCR_MODEL` provide optional task overrides, with the primary/utility settings retained as fallbacks. Vision, ASR, TTS, image generation, and video generation are not configured. Responses API storage is disabled with `store=False`; provider retention remains governed by applicable provider terms, with no zero-retention claim. Only `OPENAI_API_KEY` configures model access, and requests cannot choose a provider or model. Final model promotion remains pending held-out evaluation. Each chat-executable operation uses the same typed command handler as its manual API action; consequential plans require explicit confirmation.

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm. Media rendering additionally requires FFmpeg and ffprobe on `PATH`.

Create a local `.env` from `.env.example`, configure registration and the OpenAI key as described below, then run the backend:

```powershell
cd backend
uv sync --locked
uv run alembic -c alembic.ini upgrade head
uv run python -m app
```

In a second terminal, run the generation worker:

```powershell
cd backend
uv run python -m app.job_worker
```

The default worker polls every second while idle; `--once` makes one claim attempt, processes at most one job, and exits.

For media rendering, run a separate CPU worker:

```powershell
cd backend
uv run python -m app.job_worker --resource-class media_cpu
```

In a third terminal, run the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL (usually `http://localhost:5173`). Its `/api` proxy targets the backend port.

## Sign-in and model setup

Passwords are never stored in plaintext. They are hashed with Argon2id using a unique library-generated salt (19,456 KiB memory, 2 iterations, parallelism 1). Passwords must be 15–128 characters; Unicode, spaces, and passphrases are allowed without composition rules. Usernames are trimmed, lowercased, and unique; they use 3–64 ASCII letters, numbers, dots, underscores, or hyphens.

Registration is disabled by default with `SIH_ALLOW_REGISTRATION=false`. For a Railway demo, temporarily set it to `true`, redeploy, register the required demo account(s), set it back to `false`, and redeploy. No password belongs in environment configuration or this repository. Local application sessions remain random, HttpOnly, Secure outside development, SameSite=Lax, eight hours long, and stored as a digest at rest.

Put the OpenAI API key in `OPENAI_API_KEY` in the root `.env`. Keep `.env` private and never commit credentials. `SIH_DATABASE_URL` defaults to `sqlite:///./axiomweave.db`, relative to the backend working directory. `SIH_HOST` and `SIH_PORT` control the local server; use the same backend port for Vite's proxy.

## Checks

From `backend/`:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

From `frontend/`:

```powershell
npm ci
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

## PostgreSQL integration tests

SQLite remains the local default. PostgreSQL migration and runtime compatibility is tested with the pinned PostgreSQL 17 and pgvector image. Start it bound to loopback:

```powershell
docker run --rm -d --name axiomweave-postgres-test `
  -e POSTGRES_USER=axiom -e POSTGRES_DB=postgres -e POSTGRES_HOST_AUTH_METHOD=trust `
  -p 127.0.0.1:55432:5432 pgvector/pgvector:0.8.6-pg17-bookworm
docker exec axiomweave-postgres-test pg_isready -U axiom -d postgres
$env:AXIOMWEAVE_TEST_POSTGRES_URL = "postgresql+psycopg://axiom@127.0.0.1:55432/postgres"
cd backend
uv run pytest tests/test_postgres_migrations.py -q
docker stop axiomweave-postgres-test
```

The PostgreSQL tests create uniquely named databases, apply the migration chain, exercise ORM persistence, and verify that pgvector 0.8.6 can be enabled. The disposable local test instance uses trust authentication and must remain bound to loopback.

## Phase 2 retrieval and evidence

Every new generation Job records the exact source pack version, selected factual regions, role, locator, content hash, budget estimate, coverage state, and warnings in an immutable `ContextManifest`. The worker reconstructs context from that manifest instead of rerunning selection. R0 includes all eligible PRIMARY and SUPPORTING text when it fits the versioned 20,000-character context budget; partial extraction stays visible, and over-budget work waits for review because no R1 profile is admitted for generation.

PostgreSQL native full-text search uses the `simple` configuration and is called PostgreSQL FTS, not BM25. On the four-pack, six-task fixture, top-2 FTS recalled 2/7 required regions and 1/4 qualifier regions, missing four tasks. It used 117 of R0's 785 source-region characters, an 85.1% reduction, but remains an unpromoted candidate. Exact pgvector and reciprocal-rank fusion are mechanics-only; no semantic embedding profile is selected. See [`backend/evals/retrieval/README.md`](backend/evals/retrieval/README.md) for denominators, latency, and limitations.

Claim scans have no global claim-count ceiling. Their visible completion state derives from every persisted batch. An exact source quote proves only that the quotation occurs in that source; a `KnowledgeAssertion` is a provenance-bearing candidate, not a verified fact.

New artifact versions receive deterministic addressable text blocks and a resumable claim-scan record. Lineage IDs and quotes from a model are stored as proposals and are validated against the exact selected ContextManifest, source role, region, and span before a dependency is created. Quote location and semantic evidence assessments are separate states. Semantic verification does not establish ground truth and can misjudge entailment, polarity, scope, attribution, or qualifiers; unresolved and consequential cases remain reviewable. No verifier accuracy or factuality percentage is claimed.

Historical artifact versions remain lineage-unavailable until re-analysis. The Phase 4 migration does not invent historical artifact blocks, lineage proposals, evidence assessments, review decisions, or source-region alignments.

Source revision impact uses exact-content SourceRegion alignment and content-addressed block dependencies. Ambiguous, split, merged, or incomplete provenance does not authorize targeted edits. A safe selective revision accepts replacements only for server-authorized affected blocks, reconstructs the family artifact on the server, and writes a new draft ArtifactVersion. Accepted versions remain immutable. Review decisions record workflow choices for exact versions and do not certify factual accuracy.

## Scope and limitations

PDF OCR is a model-assisted fallback for scanned pages with little usable native text. It is not guaranteed to be perfect. PDF uploads are limited to 8 MiB and 20 pages; no more than 8 pages are sent for OCR. URL import supports public HTTP/HTTPS text and HTML pages up to 2 MiB, with at most three validated redirects; extracted text is limited to 20,000 characters without truncation. It does not log in, execute JavaScript, or crawl. Evidence analysis proposes claims with a model, but the application verifies each proposed quotation against the exact selected manifest region; this is traceability support, not a guarantee that every claim is complete or true. Discrepancy findings are review prompts. Legacy source-segment diffs remain display information; deterministic source-region alignments and validated block dependencies govern revision impact. Phase 5 adds bounded source image/audio/video ingestion, provider-neutral multimodal extraction interfaces, deterministic infographic/video rendering, private media previews, and an explicit human review gate; operational limits and provider constraints are described above. The local SQLite setup is for development and demonstration, not a production deployment recipe.

## SIH deliverables

This repository provides the source code, setup and configuration guidance, tests, and architecture overview. The SIH demo video (maximum 2 minutes) and technical presentation (maximum 5 slides) are separate submission materials.
