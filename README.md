# SIH26154 — Content Transformation

## Problem

SIH26154, proposed by NTRO for Smart India Hackathon 2026, explores transforming source content into communication artifacts for different audiences and purposes.

## Current capability

Operators can enter text, select multiple output types, and set the audience, tone, language, detail level, communication objective, and content style. The backend validates and prepares this request through `POST /api/transformations/prepare`; `GET /api/health` remains available for connectivity checks.

Model-based generation and artifact creation, artifact validation, file/image/video ingestion, and review/history workflows are not implemented.

## Architecture

Current flow: `Browser → React/Vite frontend → HTTP API → FastAPI health and request preparation`.

See [docs/architecture.md](docs/architecture.md) for the implemented path and planned product flow.

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and npm.

From the repository root, start the backend:

```powershell
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

Open the URL printed by Vite (usually http://localhost:5173). The development server proxies `/api` requests to the backend.

## Configuration

The backend accepts plain text up to 20,000 characters per request. Other controls are bounded and validated by the backend. Backend settings use safe defaults; to override them locally, copy [.env.example](.env.example) to `.env` in the repository root or set the variables in your shell.

If you change `SIH_PORT`, set it in both the backend and frontend terminal environments so the development proxy uses the same port.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIH_ENVIRONMENT` | `development` | Runtime environment label |
| `SIH_HOST` | `127.0.0.1` | Backend bind address |
| `SIH_PORT` | `8000` | Backend port |

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
