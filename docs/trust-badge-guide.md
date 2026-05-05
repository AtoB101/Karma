# Trust Badge Guide (Karma Guard)

The **Karma Protected Badge** is a public trust display for sellers and agent
service providers.

This guide documents what can be shown publicly and how to embed the badge.

## 1) Public badge fields

- `seller_wallet`
- `total_protected_volume`
- `verified_orders`
- `success_rate`
- `dispute_rate`
- `active_bond_amount`

These values are safe summary indicators.

## 2) What this badge does not expose

- Private scoring weights
- Internal anti-fraud thresholds
- Internal arbitration weight matrix
- Internal risk engine model outputs beyond public-safe reason codes

## 3) Demo badge page

Local demo route:

- `apps/agent-service-guard/frontend/badge.html?seller_wallet=<wallet>`

The page includes a **Copy Embed Code** action with a simple HTML snippet.

## 4) Suggested embed pattern

```html
<iframe
  src="https://your-domain.example/agent-service-guard/badge.html?seller_wallet=0xSeller..."
  title="Karma Protected Badge"
  width="420"
  height="260"
  style="border:0;"
></iframe>
```

If using a custom HTML badge component, keep metrics synchronized from public
API outputs or approved public cache only.

## 5) Display policy

- Badge must not imply guaranteed outcomes.
- Badge must not expose private customer identities or order payloads.
- Badge should include a short note: "Derived from public-safe protected
  transaction summaries."
