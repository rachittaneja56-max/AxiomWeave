# SIH26154 architecture

## Current system and flow

CODEX 00 is a small modular-monolith foundation. A React and TypeScript page is served by Vite. During development, Vite proxies the page's health request to a FastAPI backend. The backend currently exposes only `GET /api/health`; it has no persistence or generation path.

```text
Current:  Browser → Vite frontend → /api/health → FastAPI

Planned:  Text Source → Transformation Request → Generation Boundary
          → Draft Artifact → Human Review
```

The planned flow is a product direction, not implemented behavior. It will transform text input into selected textual artifact drafts. The application will orchestrate a generation provider through a narrow backend boundary; the model will not receive shell, database, browser, or tool access.

## Decisions and boundaries

- **Modular monolith:** one backend application keeps the initial deployment and code structure small. API transport and configuration are separated from future domain and provider code.
- **Frontend boundary:** the browser calls the backend API through an HTTP boundary. The Vite proxy is development-only.
- **Provider boundary:** a model provider is planned behind an application-controlled generation boundary. No provider or live model call exists yet.
- **Versioning:** immutable source snapshots and artifact history are planned for later work; no source or artifact is persisted in this foundation.
- **Untrusted content:** source text will be treated as data, separate from application instructions and operator settings. Model output will require structural and size validation before display.
- **Persistence direction:** SQLite with SQLAlchemy and migrations may be introduced when a focused task adds persistence. There is no database dependency or schema now.
- **Verification:** backend tests cover the HTTP health behavior and safe settings defaults. Frontend tests cover rendering and health success/failure states; lint, formatting, type checks, and a production build provide additional checks.
- **Experiment boundary:** retrieval, shared-fact runtime, lineage, semantic sibling checking, revision dependency logic, agents, and other experiment-dependent mechanisms are excluded from this MVP foundation.
