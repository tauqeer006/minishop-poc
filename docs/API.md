# API reference (summary)

Interactive docs: http://localhost:8000/docs. Base path `/api/v1`. JSON only.

**Success:** `{"success": true, "data": ..., "request_id": "..."}` ·
**Error:** `{"success": false, "error": {"code": "INSUFFICIENT_STOCK", "message": "...", "details"?: {}}, "request_id": "..."}`
(never tracebacks). Every response carries `X-Request-ID` and `X-Trace-Id`. Clients may send `X-Request-ID`,
W3C `traceparent`, `X-Client-Version` (e.g. `1.0.0`), `X-Client-Id`. Money is integer minor units (cents).

| Auth | Method & path | Notes |
|---|---|---|
| – | `POST /auth/register` `{name,email,password}` | 201, role always `customer` |
| – | `POST /auth/login` | returns `access_token` (JWT) |
| user | `GET /auth/me` | |
| – | `GET /products?search&page&page_size` | public; admin may add `include_inactive=true` |
| – | `GET /products/{id}` | **APP-R-056 monitored endpoint** |
| admin | `POST /products` | validated; price > 0, stock ≥ 0 |
| admin | `PATCH /products/{id}` | `expected_version` → strict optimistic lock (409 `VERSION_CONFLICT`); `stock_delta` or `stock_quantity` |
| user | `POST /orders` | **requires `Idempotency-Key`** header; body `{items:[{product_id,quantity}]}`; 201 new, 200 replay |
| user | `GET /orders`, `GET /orders/{id}` | customers see only their own (admin sees all) |
| admin | `GET /admin/dashboard` | totals |
| admin | `GET /admin/orders?status&page` | includes customer name/email |
| admin | `PATCH /admin/orders/{id}/status` `{status,note?,workflow_execution_id?}` | state machine; envelope has `duplicate` |
| admin | `GET /admin/events`, `GET /admin/audit-logs` | filters + pagination |
| admin | `GET /admin/performance/endpoints \| metrics \| baselines \| incidents \| traces/{trace_id}` | APP-R-056 |
| admin, dev only | `GET/POST /dev/state`, `POST /dev/reset`, `POST /dev/monitoring/close-window` | mounted only when `ENABLE_DEV_SCENARIOS=true` and `ENVIRONMENT != production` |
| – | `GET /health` | DB ping |

Order statuses: `PENDING → CONFIRMED → SHIPPED → DELIVERED`; `PENDING|CONFIRMED → CANCELLED` (cancel restocks once).

Stable error codes: `MALFORMED_JSON`, `REQUEST_SCHEMA_INVALID` (400, APP-R-001) · `INVALID_DOMAIN_VALUE` (400, APP-R-020)
· `CLIENT_VERSION_UNSUPPORTED` (426, APP-R-002) · `INSUFFICIENT_STOCK`, `PRODUCT_UNAVAILABLE`,
`INVALID_STATUS_TRANSITION` (409, APP-R-004) · `IDEMPOTENCY_KEY_REQUIRED/INVALID` (400), `IDEMPOTENCY_KEY_REUSED` (409, APP-R-021)
· `VERSION_CONFLICT` (409, APP-R-040) · `DEPENDENCY_UNAVAILABLE` (503, APP-R-030) · `AUTH_REQUIRED` (401),
`INVALID_CREDENTIALS` (401), `FORBIDDEN` (403) · `INTERNAL_ERROR` (500).

Note: FastAPI's default 422 is deliberately replaced by 400 (APP-R-001/020).
