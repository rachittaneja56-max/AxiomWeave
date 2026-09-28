# SIH26154 architecture

## Implemented system

```text
Browser → React/Vite frontend → HTTP API → FastAPI
                                      ├→ GET /api/health
                                      └→ POST /api/transformations/prepare
```

The browser submits direct text and operator-selected settings. The backend validates and returns the canonical request as ready for a later stage. No artifact content is generated.

## Planned product flow

```text
Source → Operator transformation request → Model/generation boundary
       → Requested artifact drafts → Validation and review
```

This flow is the target product direction beyond request preparation; generation, artifact validation, and review are not implemented.

## Stable boundaries

- Source content is untrusted data and does not carry application authority.
- Any model interaction remains controlled by the application.
- The frontend communicates with backend capabilities through the HTTP API.
- The system remains a small modular monolith unless implemented needs demonstrate otherwise.
