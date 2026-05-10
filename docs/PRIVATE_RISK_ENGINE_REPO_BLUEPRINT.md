# Private risk engine repository (blueprint only)

This file **describes** the intended layout of a **separate private repository** (for example `karma-private-risk-engine`).
It is safe to keep in the public tree because it contains **no rules, weights, or datasets** — only directory names.

Expected private areas (illustrative):

- `risk-engine/` — fraud / sybil / buyer / seller / agent risk implementations  
- `reputation-engine/` — scoring, decay, trust weights  
- `dispute-engine/` — classifiers, evidence weighting, decisions, appeals  
- `policy-engine/` — settlement / slash / refund / collateral policies  
- `internal-api/` — authenticated services called **only** from operator backends  
- `private-data-contracts/` — JSON schemas for internal events  

**Never** copy private implementations into this public repository.
