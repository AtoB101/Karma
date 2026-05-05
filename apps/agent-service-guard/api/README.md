# Agent Service Guard Public API (Mock + Reserved Endpoints)

This directory documents public mock API behavior and private-engine reserved endpoints.

## Mock APIs used by frontend demo

- `POST /services` create protected service
- `GET /services/{service_id}` fetch service
- `POST /orders` create protected order from service
- `GET /orders/{order_id}` fetch order
- `POST /orders/{order_id}/deliver` seller delivery submit
- `POST /orders/{order_id}/confirm` buyer confirm completion
- `POST /orders/{order_id}/dispute` buyer open dispute
- `POST /orders/{order_id}/arbitrate` admin mock arbitration
- `GET /dashboard/stats` dashboard aggregation
- `GET /badge/{seller_wallet}` seller trust badge stats

## Reserved private risk-engine endpoints (not implemented in public repo)

These are interface placeholders only:

- `POST /risk/check`
- `POST /dispute/recommend-resolution`
- `POST /score/seller`

> This endpoint set is provided by the private risk engine.
> Public repository keeps only data contracts and response adapters.
