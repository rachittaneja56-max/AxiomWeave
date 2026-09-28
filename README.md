# SIH26154 — Content Transformation MVP

## Problem

SIH26154, proposed by NTRO for Smart India Hackathon 2026, explores transforming source content into communication artifacts for different audiences and purposes.

## Current MVP scope

- **Implemented:** backend health endpoint and a development page that reports backend health.
- **Partial:** repository, configuration, and quality-check foundation.
- **Planned / out of MVP:** source handling, transformation settings, generated drafts, and human review. No generation is implemented in CODEX 00.

## Architecture

Current flow: `Browser → Vite development server → FastAPI health endpoint`.

The intended text transformation flow and design boundaries are in [docs/architecture.md](docs/architecture.md). Planned stages are not implemented.

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm.

From the repository root, create local settings and start the backend:

```powershell
Copy-Item .env.example .env
cd backend
uv sync --locked
uv run python -m app
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (usually http://localhost:5173). The Vite development server proxies `/api` to the backend.

## Configuration

Backend settings are read from the process environment or the root `.env` file. See [.env.example](.env.example):

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIH_ENVIRONMENT` | `development` | Runtime environment label |
| `SIH_HOST` | `127.0.0.1` | Backend bind address |
| `SIH_PORT` | `8000` | Backend port |
| `SIH_LOG_LEVEL` | `INFO` | Structured log threshold |

## Development checks

Backend, from `backend/`:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
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

## Current limitations

CODEX 00 does not implement source persistence, transformation requests, model providers, artifact generation, validation of generated artifacts, or review/history workflows. The health check demonstrates connectivity only.

## SIH deliverables

- [x] Source code foundation
- [x] README with setup instructions
- [x] Architecture document (kept concise for the two-page limit)
- [ ] Demo video (maximum 2 minutes)
- [ ] Technical presentation (maximum 5 slides)
