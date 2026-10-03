# AxiomWeave

**Source-Grounded Content Transformation Workspace**

AxiomWeave turns one source and communication brief into a set of audience-ready artifacts. It helps teams reuse authoritative material while keeping each output tied to its source, review history, and later revisions.

## What is implemented

- Seven artifact families: executive summary, LinkedIn post, X post, formal advisory, presentation, infographic, and video package.
- Versioned SourcePacks with source roles and immutable `ContextManifest` records for each generation job.
- Durable, independently retryable jobs and immutable artifact versions.
- Source quotations, validated lineage, evidence assessments, discrepancy review, and selective source revision.
- ActionPlans that propose allowlisted typed commands, recheck workspace state, and require confirmation for consequential actions.
- Deterministic infographic and video rendering, private media storage, and explicit media-rights records.
- Password-based accounts, owner-scoped data access, audit and model-usage records, and request rate limits.

## Architecture

The frontend is React and Vite. The backend is a FastAPI and SQLAlchemy modular monolith. SQLite is the local default; PostgreSQL migrations and runtime behavior are covered by integration tests. Artifact generation and media rendering run in separate database-backed workers. Original uploads and rendered files use a private local asset directory by default, with optional S3-compatible private storage for shared production assets. See [docs/architecture.md](docs/architecture.md) for data flow, security boundaries, and rendering details.

## Setup

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm. FFmpeg and ffprobe are required to render media.

Create the local environment file from the example and set `OPENAI_API_KEY` to enable model-backed operations:

```powershell
Copy-Item .env.example .env
```

`SIH_DATABASE_URL` defaults to `sqlite:///./axiomweave.db`; `SIH_PRIVATE_ASSET_DIR` selects private file storage, and `SIH_PRIVATE_ASSET_BACKEND` defaults to `local`. Production can select `s3` and set `SIH_S3_BUCKET`, `SIH_S3_ENDPOINT`, and `SIH_S3_REGION`, with credentials supplied through `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Registration is disabled by default. For a local demo, set `SIH_ALLOW_REGISTRATION=true` while creating accounts, then disable it. The configured model defaults are `gpt-6-luna` for generation and analysis and `gpt-5-nano` for scanned-page OCR. Task-specific environment variables can override these defaults. Requests cannot select a provider or model.

## Run the application

Run database migrations and the API from `backend`:

```powershell
Set-Location backend
uv sync --locked
uv run alembic -c alembic.ini upgrade head
uv run python -m app
```

In another terminal, start the artifact worker:

```powershell
Set-Location backend
uv run python -m app.job_worker
```

Start a separate media worker when rendering infographics or video packages:

```powershell
Set-Location backend
uv run python -m app.job_worker --resource-class media_cpu
```

A single worker may run in `combined` mode for constrained/demo deployments; production-scale deployments may run separate `model_io` and `media_cpu` workers.

Run the frontend in a third terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the Vite URL printed in the terminal, usually `http://localhost:5173`.

## Tests and checks

From `backend`:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

PostgreSQL integration tests run when `AXIOMWEAVE_TEST_POSTGRES_URL` points to a test database. CI runs these tests against PostgreSQL 17 with pgvector.

From `frontend`:

```powershell
npm ci
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

## Current limitations

Vision, audio transcription, speech synthesis, and generated image or video providers are not configured. Scanned-page OCR is model-assisted, and evidence analysis supports review rather than proving that claims are true or complete. URL import reads bounded public pages; it does not sign in, execute JavaScript, or crawl. SQLite and local file storage remain the development defaults; PostgreSQL and the optional S3-compatible backend support shared production services.

The SQLite backup utility supports local demo data and checks database integrity and private-asset hashes. From `backend`, use `uv run python -m scripts.sqlite_recovery backup <database> <assets> <new-backup-directory>`.
