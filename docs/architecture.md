# SIH26154 architecture

## Implemented system

```text
Browser → React/Vite frontend → HTTP API → FastAPI
```

The frontend calls `GET /api/health` through the backend API. This is the only current application path; content transformation is not implemented.

## Planned product flow

```text
Source → Operator transformation request → Model/generation boundary
       → Requested artifact drafts → Validation and review
```

This flow describes the target MVP direction, not existing behavior.

## Stable boundaries

- Source content is untrusted data and does not carry application authority.
- Any model interaction remains controlled by the application.
- The frontend communicates with backend capabilities through the HTTP API.
- The system remains a small modular monolith unless implemented needs demonstrate otherwise.
