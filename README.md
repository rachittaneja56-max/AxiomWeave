# AxiomWeave — SIH26154

**Source-Grounded Content Transformation Workspace**

One source. Many artifacts. Every claim traceable.

## Problem and solution

Teams often rewrite the same authoritative material for several audiences and formats. Manual reuse can introduce drift, hide unsupported claims, and make later source corrections hard to apply. AxiomWeave is a source-grounded content transformation workspace for saving a source and communication brief once, generating five related deliverables, and reviewing each version with its source provenance visible.

## Tier-A workflow

- Username/password sign-in and an owner-scoped transformation dashboard.
- Paste source text, upload `.txt`, `.md`, `.docx`, or `.pdf`, or import one public HTTP/HTTPS article URL; keep supporting context separate. DOCX paragraphs, headings, and tables are extracted. PDFs use native text extraction first; scanned pages use OCR/Vision only when native text is unavailable. URL import reads one public page without login, JavaScript rendering, or crawling.
- Set audience, tone, language, detail, objective, and style.
- Generate an Executive Summary, Professional / LinkedIn Post, X Post, Formal Advisory, and Presentation with speaker notes. X Post is one source-grounded update capped at 280 Unicode code points. A failed output can be retried independently.
- Review and edit immutable artifact versions; accept or reject drafts.
- Inspect exact source quotations and unsupported claims. Compare sibling outputs for possible discrepancies, then dismiss a finding without changing artifact text.
- Save source V2, inspect a deterministic paragraph diff and potentially affected evidence, run a targeted update, or regenerate fully from V2.
- Copy artifact text or download Markdown. Presentations also export as editable PowerPoint slides with speaker notes.

## Architecture

The application is a React/Vite frontend and a FastAPI/SQLAlchemy modular monolith backed by SQLite for local use. AxiomWeave uses first-party username/password authentication for the Tier-A MVP. Password authentication is not phishing-resistant; it is the selected demo authentication method. Phase 1B adds owner-scoped Source Packs, immutable pack versions, explicit source authority, and addressable regions while retaining the SourceVersion projection required by existing generation and review code. Uploaded bytes use a private local storage directory configured by `SIH_PRIVATE_ASSET_DIR`; production object storage and multimodal processing are not implemented. Generation uses the OpenAI Responses API through a provider boundary, with structured output for presentations, evidence proposals, discrepancy analysis, and targeted updates. `docs/architecture.md` gives the data and request flow.

Primary artifact generation uses `gpt-6-luna`; evidence and discrepancy analysis plus scanned-page OCR use `gpt-5-nano` by default. The server applies code-owned output-token limits and disables Responses API storage. Set `SIH_OPENAI_UTILITY_MODEL` to override the utility model. Only `OPENAI_API_KEY` configures model access. The provider cannot be selected by request data.

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm.

Create a local `.env` from `.env.example`, configure registration and the OpenAI key as described below, then run the backend:

```powershell
cd backend
uv sync --locked
uv run alembic -c alembic.ini upgrade head
uv run python -m app
```

In another terminal:

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

## Scope and limitations

PDF OCR is a model-assisted fallback for scanned pages with little usable native text. It is not guaranteed to be perfect. PDF uploads are limited to 8 MiB and 20 pages; no more than 8 pages are sent for OCR. URL import supports public HTTP/HTTPS text and HTML pages up to 2 MiB, with at most three validated redirects; extracted text is limited to 20,000 characters without truncation. It does not log in, execute JavaScript, or crawl. Evidence analysis proposes claims with a model, but the application verifies each proposed quotation as an exact substring of its saved source version; this is traceability support, not a guarantee that every claim is complete or true. Discrepancy findings are review prompts. Source diffs are deterministic paragraph comparisons. Standalone image input, video input, RAG, infographic rendering, and video package generation are not implemented. The local SQLite setup is for development and demonstration, not a production deployment recipe.

## SIH deliverables

This repository provides the source code, setup and configuration guidance, tests, and architecture overview. The SIH demo video (maximum 2 minutes) and technical presentation (maximum 5 slides) are separate submission materials.
