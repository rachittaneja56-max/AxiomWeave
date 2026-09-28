# AxiomWeave — SIH26154 content transformation

**Source-Grounded Content Transformation Workspace**

One source. Many artifacts. Every claim traceable.

SIH26154 is the Smart India Hackathon 2026 problem statement. AxiomWeave is the product name.

## Current implementation

The React/Vite frontend lets authenticated operators paste text or upload UTF-8 `.txt` / `.md` files, add separate supporting context, select the four Tier-A output types, and set audience, tone, language, detail, objective, and style. Saving creates an owner-scoped `Source`, immutable `SourceVersion` with a SHA-256 content hash, deterministic `SourceSegment` rows, and a `TransformationRun` snapshot. Source transport normalization removes a leading BOM and normalizes line endings while preserving other characters; source content is bounded at 20,000 characters and supporting context at 5,000 characters.

The SQLite schema and existing Alembic migration include users, sessions, sources, source versions and segments, transformation runs, artifact runs, and artifact versions. The save route now persists the source and transformation brief; artifact records remain unused by the user workflow.

Google Identity Services provides browser sign-in, and the backend verifies the Google ID token against `SIH_GOOGLE_CLIENT_ID`. AxiomWeave maps the verified Google `sub` to a local user and issues a separate eight-hour application session in an HttpOnly, SameSite=Lax cookie. Only the session token digest is stored. Logout revokes the local session. Text-file extraction and transformation routes require a valid local session; health remains public. The save action derives owners only from the authenticated user and commits the source and transformation snapshot in one transaction. Owner-scoped query functions cover the persisted source, source-version, transformation-run, artifact-run, and artifact-version hierarchy.

Artifact generation is still not user-facing. The transformation-save action does not create `ArtifactRun` rows and does not generate content. A generation provider protocol and internal Executive Summary logic exist, but no live provider is connected. The dashboard, artifact review/history, evidence links, discrepancy warnings, source revision analysis, targeted updates, and export are not implemented. Segments are source structure only and do not constitute evidence links. Structural validation and internal generation do not establish factual correctness.

## Architecture

The implemented save path is `Authenticated user → source normalization → Source / SourceVersion / SourceSegments → TransformationRun`. The existing generation boundary remains separate and is not connected to this save action. Health remains public; see [docs/architecture.md](docs/architecture.md) for the implemented path and boundaries.

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
| `SIH_GOOGLE_CLIENT_ID` | unset | Google OAuth Web application client ID; passed to Vite as the public GIS client ID |

For local or demo sign-in, create a Google OAuth Web application client and add the actual frontend origin to its authorized JavaScript origins (for example, the Vite development origin). Add the final demo origin when it is known. GIS callback mode does not require a redirect URI, Google client secret, or Drive scope. Keep `.env` local and do not commit credentials.

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
