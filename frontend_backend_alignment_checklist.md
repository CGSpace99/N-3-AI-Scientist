# Frontend-Backend Alignment Checklist

This checklist locks request/response contract alignment between `Frontend_Final` and backend persona endpoints.

## Contract Lock

- [x] Canonical persona routes aligned: `/api/chat/{rachael|eric|faith}` -> `/api/frontend/chat/{rachael|eric|faith}` proxy.
- [x] Canonical frontend response key casing preserved (`jobId`, `similarityFlag`, `trailSteps`, `planUpdate`, `readinessScore`).
- [x] Frontend backend URL moved to env (`Frontend_Final/.env.local` -> `API_URL`).

## Request Normalization

- [x] Normalize chat message roles at boundary:
  - UI role `character` -> backend role `assistant`
  - preserve canonical roles `user | assistant`
- [x] Frontend request payload serialization updated to send normalized roles for all personas.
- [x] Backend frontend request schema accepts compatibility role values and normalizes before use.

## Mapper Layer

- [x] Backend mapper utility module in place (`ai_scientist/frontend_contract.py`) for:
  - paper mapping
  - novelty flag mapping
  - trail step mapping
  - inventory section mapping + patch merge
  - plan formatting
- [x] Backend persona endpoints return frontend-required naming and shape.

## Error and UX Alignment

- [x] Frontend Rachael flow surfaces backend `detail` errors in chat.
- [x] Frontend Rachael flow shows visible progress text while backend QC is running.
- [x] Next route proxies preserve backend error status and JSON when available.

## Validation Coverage

- [x] Added/updated API contract tests for frontend persona routes.
- [x] Added compatibility test for mixed role history (`character` entries) accepted through backend frontend endpoint.
- [x] Add stricter response-key snapshot tests for all three persona routes.
- [ ] Add contract-version marker (`X-Contract-Version` or payload field) for future schema migration safety.
