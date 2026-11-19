# Implemented now vs. reserved for the next phase

## Implemented in this phase
* Working application (React, FastAPI, MongoDB replica set, Docker Compose) with customer and admin functionality
* Baseline validation and business protections (APP-R-001, 002, 004, 020, 021, 030, 040, 041): schema/domain validation,
  version compatibility, transactional inventory with conditional updates, idempotency, optimistic locking, state machine,
  workflow de-duplication, bounded jittered retries for idempotent reads
* Structured event logging (`application_events`) and audit logging (`audit_logs`), no secrets stored
* Endpoint latency instrumentation, per-window avg/P95/P99, historical baselines with contamination protection
* Threshold-based sustained-degradation detection and incident records (`rectification_incidents`)
* OpenTelemetry-compatible distributed tracing and trace-based bottleneck evidence (measured)
* Controlled fault scenarios (`scenarios/run_scenarios.py`, dev-only)
* ML integration interfaces (`rectification/ml_interface.py`: input builder, output contract, `FaultIdentifier` protocol,
  general-feature extractor)
* Corrective-action registry **definitions** (`action_registry.py`), execution bookkeeping (`record_action_execution`),
  verification and escalation logic (`verify_recovery`, `escalate`) — exercised by tests with controlled inputs

## Reserved for the next phase (NOT implemented, NOT operational)
* ML model training and inference; ML-based fault classification and root-cause diagnosis (incident `diagnosis` stays
  `AWAITING_ML_MODEL`; the UI shows no confidence)
* Autonomous rule selection
* Controlled automatic corrective-action execution (no `ActionExecutor` implementation exists; actions are only *proposed*)
* Automated post-rectification recovery management and rollback execution (verification logic exists; nothing triggers an
  action, and rollback is only *requested* in the incident record)
* Approval workflow for MEDIUM/HIGH risk actions (the registry flags them; there is no approval UI/API)

## Where the future components connect
1. **Feature extraction:** read `rectification_incidents.ml_diagnosis_input` (APP-R-056) and
   `ml_interface.extract_general_features()` (other rules) from `application_events`.
2. **Model:** implement `FaultIdentifier.identify(ml_input) -> FaultDiagnosis`; write the validated result into
   `incident.diagnosis` (set `status`, `probable_cause`, `confidence`; the dashboard then shows it under "ML diagnosis").
3. **Rule/action selection:** map `FaultDiagnosis.recommended_action` through `action_registry.ACTIONS`
   (check `requires_approval`, `reversible`, `restrictions`).
4. **Execution:** implement `ActionExecutor`, call `performance_service.record_action_execution()` immediately before
   executing (it enforces once-per-action, approval and attempt budget).
5. **Verification & escalation:** already driven by `close_window()` → `verify_recovery()` → `escalate()`.

Any new action must be predefined, tested, reversible, and must never modify source code, DB-server configuration or
infrastructure, disable authentication/validation, or introduce unsafe caching.
