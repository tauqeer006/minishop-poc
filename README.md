# MiniShop — Application-Level Intelligent Fault Rectification POC

A small e-commerce / order-management application (React + FastAPI + MongoDB) built as a research
environment for **application-level fault detection and rectification**. It contains real business
workflows, structured observability (events, traces, latency windows, baselines) and controlled fault
scenarios for nine rectification rules (APP-R-001, 002, 004, 020, 021, 030, 040, 041 and the new **APP-R-056**
API response-time degradation rule).

> **Scope of this phase.** Implemented: the application, protections for the eight original rules,
> structured events, endpoint latency monitoring, historical baselines, threshold-based sustained-degradation
> detection, distributed tracing, trace-based bottleneck evidence, incident records, verification/escalation logic,
> controlled scenarios, ML-interface contracts and the corrective-action registry **definitions**.
> **Not implemented (next phase):** any ML model/inference and any automatic corrective-action execution.
> See [docs/FUTURE_RECTIFICATION.md](docs/FUTURE_RECTIFICATION.md).

## Technology stack
Frontend: React 18, Vite, React Router, Axios, Tailwind CSS, Context API · Backend: Python 3.12, FastAPI, Pydantic,
PyMongo (async), JWT (PyJWT) + bcrypt, structured JSON logging, OpenTelemetry-compatible tracing (W3C `traceparent`,
32/16-hex ids) · Database: MongoDB 7 single-node replica set (required for transactions) · Docker Compose.

## Architecture
```
Browser ──> React (Vite :3000, proxies /api -> backend)
              │
              v
         FastAPI :8000 ── ObservabilityMiddleware (request/trace ids, version check, latency sample, spans)
              │                │
              v                v
          services ──> MongoDB rs0 :27017   (users, products, orders, application_events, audit_logs,
              │                               api_latency_metrics, api_latency_baselines, trace_spans,
              │                               rectification_incidents, + latency_samples [raw, TTL])
              └─ rectification/: rule_catalog · action_registry (definitions only) · ml_interface (contracts only)
```
Business logic, observability, (future) ML diagnosis, (future) rule-based rectification and verification are
separate concerns; nothing in the business path calls ML.

## Prerequisites
Docker Desktop / Docker Engine with Compose v2. (Optional for scenario runner: Python 3.9+; no packages needed.)

## Start
```bash
cp .env.example .env        # optional; defaults already work
docker compose up --build -d
```
| URL | |
|---|---|
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| MongoDB | `mongodb://localhost:27017/?directConnection=true` |

The browser only talks to `http://localhost:3000/api/...`; the Vite dev server proxies to `http://backend:8000`
inside the Docker network (no Docker-internal hostnames in browser code). First start takes a minute: MongoDB's
healthcheck initiates the replica set (`rs0`), then the backend waits for the primary, creates indexes and seeds data.

Stop: `docker compose down` (data persists in the `mongo_data` volume; `docker compose down -v` wipes it).

## Development login credentials (seeded, development only)
| Role | Email | Password |
|---|---|---|
| Administrator | `admin@minishop.dev` | `Admin@12345` |
| Customer | `customer1@minishop.dev` | `Customer@12345` |
| Customer | `customer2@minishop.dev` | `Customer@12345` |

Configurable via `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_CUSTOMER_PASSWORD`. The seed refuses default
passwords when `ENVIRONMENT=production`. Seeding is idempotent (safe on every start).

## Environment configuration
See [.env.example](.env.example). Key variables: `ENVIRONMENT`, `MONGO_URI`, `MONGO_DB_NAME`, `JWT_SECRET`,
`ENABLE_DEV_SCENARIOS` (dev fault-injection endpoints; forced off in production), `MONITOR_WINDOW_SECONDS`,
`TRACE_SAMPLE_RATE`, plus threshold overrides (docs/PERFORMANCE_MONITORING.md).

## Tests
Tests need MongoDB with a replica set (transactions). They create a **disposable database**
`minishop_test_<random>` on the compose MongoDB and drop it afterwards; the seeded `minishop` database is never touched.
```bash
docker compose up -d database
docker compose run --rm --no-deps -e TEST_MONGO_URI="mongodb://database:27017/?replicaSet=rs0" backend pytest -v
# or against the running stack:
docker compose exec backend pytest -v
```
Run a subset: `... pytest tests/test_performance.py -v`. Tests cover auth/authorization, validation, orders,
idempotency, optimistic-lock conflict, state machine, API versioning, duplicate workflows, transaction rollback,
events, and the APP-R-056 behaviours (latency capture, per-endpoint metrics, percentile maths, baselines,
contamination protection, sustained detection, isolated spikes, insufficient samples, trace evidence, incident
records, verification, failed-recovery escalation).

## Scenario runner (development only, disabled by default)
```bash
python scenarios/run_scenarios.py --enable                       # all nine rules
python scenarios/run_scenarios.py --enable --only APP-R-021,APP-R-056
```
Requires the stack running with `ENABLE_DEV_SCENARIOS=true` (compose default for development). It exits if the
backend does not expose the dev endpoints (e.g. production). Details: [docs/SCENARIOS.md](docs/SCENARIOS.md).
The APP-R-056 scenario takes ~1 minute and ends with an **OPEN incident** you can inspect in
*Admin → Performance*; three subsequent normal windows close it as `CLOSED_NO_ACTION`.

## Project layout
`frontend/` React app · `backend/app/` API (routes, services, observability, rectification) · `backend/scripts/`
index init + seed · `backend/tests/` · `database/` Mongo image + replica-set healthcheck · `scenarios/` runner ·
`docs/` documentation.

## Troubleshooting
* **Backend restarts / "MongoDB primary not available"** – the replica set initiates via the database healthcheck;
  wait ~30 s, check `docker compose logs database`. If you changed the compose service name, update `RS_HOST`.
* **Transactions fail ("Transaction numbers are only allowed on a replica set")** – the DB was started without
  `--replSet`; use the provided `database/Dockerfile`, and `docker compose down -v` to reset a stale volume.
* **Connecting from the host with a replicaSet URI hangs** – the replica set advertises `database:27017`; use
  `?directConnection=true` from the host.
* **Port already in use** – change the left side of the port mappings in `docker-compose.yml`.
* **Frontend cannot reach API** – requests go through the Vite proxy; check `docker compose logs frontend backend`.
* **Windows line endings** – the Dockerfile strips CRLF from the healthcheck script.
* **No performance windows in the dashboard** – windows close every `MONITOR_WINDOW_SECONDS` (60 s) and
  low-volume endpoints accumulate until percentiles are reliable; the scenario runner forces window closes.
