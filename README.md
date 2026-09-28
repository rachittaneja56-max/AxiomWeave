# AxiomWeave — SIH26154 content transformation

**Source-Grounded Content Transformation Workspace**

One source. Many artifacts. Every claim traceable.

SIH26154 is the Smart India Hackathon 2026 problem statement. AxiomWeave is the product name.

## Current implementation

The React/Vite frontend prepares a bounded text transformation request. Operators can paste text or upload UTF-8 `.txt` / `.md` files, select output types, and set audience, tone, language, detail, objective, and style. The FastAPI backend provides health checking, stateless text-file extraction, and request validation. An internal Executive Summary generator and provider protocol exist, but they are not exposed through a user-facing generation API and no live provider is connected.

The backend now includes a SQLite persistence schema and Alembic migration for users, sessions, sources, source versions and segments, transformation runs, artifact runs, and artifact versions. The schema models source and artifact version history; the application does not yet save user workflows through API routes.

The following workflows are not implemented: Google authentication, session issuance, owner isolation at the API layer, saved-source APIs, user-facing generation, review/history UI, source evidence, discrepancy warnings, source revision and targeted updates, and export. Database ownership fields alone do not enforce API access control. Structural validation and internal generation do not establish factual correctness.

## Architecture

The implemented request path is `Browser → React/Vite → FastAPI health, text extraction, and request preparation`. The backend also has a SQLAlchemy persistence boundary and SQLite migration. Persistence is not connected to the existing API routes. See [docs/architecture.md](docs/architecture.md) for the implemented path and boundaries.

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm.

From the repository root, initialize the local database schema and start the backend:

```powershell
cd backend
uv sync --locked
uv run alembic -c alembic.ini upgrade head
uv run python -m app
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (usually http://localhost:5173). The development server proxies `/api` requests to the backend.

## Configuration

The backend accepts plain text up to 20,000 characters per request. Other controls are bounded and validated by the backend. Backend settings use safe defaults; to override them locally, copy [.env.example](.env.example) to `.env` in the repository root or set the variables in your shell.

If you change `SIH_PORT`, set it in both the backend and frontend terminal environments so the development proxy uses the same port. `SIH_DATABASE_URL` defaults to `sqlite:///./axiomweave.db`, relative to the backend working directory. SQLite database, WAL, and SHM files are ignored by Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIH_ENVIRONMENT` | `development` | Runtime environment label |
| `SIH_HOST` | `127.0.0.1` | Backend bind address |
| `SIH_PORT` | `8000` | Backend port |
| `SIH_DATABASE_URL` | `sqlite:///./axiomweave.db` | Local relational database URL |

## Development checks

Backend, from `backend/`:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Frontend, from `frontend/`:

```powershell
npm ci
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

## SIH submission materials

This repository contains the source code, setup instructions, and architecture document. The demo video (maximum 2 minutes) and technical presentation (maximum 5 slides) are separate submission materials.
