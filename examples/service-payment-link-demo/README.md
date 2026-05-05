# Service Payment Link Demo (Public)

This example shows a public-safe seller flow:

1. Create a service in `apps/agent-service-guard/frontend/service-create.html`
2. Obtain `payment_link = /pay/{service_id}`
3. Share payment link to buyer
4. Buyer opens payment page and creates protected order
5. Continue in order detail page for evidence/dispute flow

No private risk scoring or arbitration internals are included.
