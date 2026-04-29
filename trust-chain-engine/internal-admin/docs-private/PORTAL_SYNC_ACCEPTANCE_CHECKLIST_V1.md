# Portal Sync Acceptance Checklist V1

## Scope
Validate Trust-Chain portal as synchronized entrypoint between frontend and backend APIs.

## Pre-check
- [ ] MVP server running on `:8822`
- [ ] Dashboard page loads without JS errors
- [ ] `GET /api/dashboard` returns unified envelope: `ok/code/message/data`

## Contract Validation
- [ ] All API success responses include: `ok=true`, `code`, `message`, `data`
- [ ] All API failures include: `ok=false`, `code`, `message`, `data`
- [ ] Frontend displays mapped Chinese error text by code family

## Interaction Sync Validation

### A. Agent Operations
- [ ] Create Agent -> appears after forced dashboard reload
- [ ] Pause/Resume Agent -> status changes after reload
- [ ] Delete Agent -> removed after reload

### B. Allowance Operations
- [ ] Stop authorization -> `stopped=true` and active额度=0
- [ ] Increase authorization -> allowance increases and active recalculated

### C. Bill Operations
- [ ] Confirm bill: `PendingConfirm -> PendingSettle`
- [ ] Reject bill: `PendingConfirm -> Disputed`
- [ ] Settle bill: `PendingSettle -> Paid`
- [ ] Dispute bill: `Paid -> Disputed`
- [ ] Strategy switch updates `payStrategy`
- [ ] Batch settle now affects only (`PendingSettle` + `now`) bills

## UX Reliability Validation
- [ ] Buttons show processing state during in-flight requests
- [ ] Inputs/controls are protected against duplicate submit while loading
- [ ] Timeout errors show human-friendly message
- [ ] Network failures show human-friendly message
- [ ] Manual refresh pulls latest backend state

## Regression Guard
- [ ] Portal still supports one-click buyer authorization
- [ ] Portal still supports one-click seller deployment
- [ ] No frontend-only state mutation without backend write

## Exit Criteria
All checks pass end-to-end in one session with no state divergence between UI and backend.
