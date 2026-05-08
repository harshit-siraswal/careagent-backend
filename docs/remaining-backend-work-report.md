# CareAgent Backend Remaining Work Report

Date: 2026-05-08

## Current Backend State

The backend repository contains a FastAPI contract skeleton, SQL migrations, OpenAPI contracts, channel/call templates, risk-engine logic, mock/simulation channel dispatch, emergency simulation fixtures, and automated tests.

Verification performed:

- `python -m compileall app` passed.
- `python -m pytest` passed with 30 tests.

## What Is Implemented

- API route skeleton for auth/session, patients, care team, consents, devices, observations, latest vitals, documents, medicines, risk events, alerts, escalation policies, escalation runs, agent messages, agent tools, and audit logs.
- Pydantic schemas for patient, document, medicine, risk, and agent contracts.
- Risk-engine rules for SpO2, glucose, heart rate, blood pressure, temperature, fall detection, stale data, quality scoring, and idempotency-key generation.
- Agent tool contract validation and policy authorization helpers.
- Mock channel dispatcher, template renderer, call script renderer, and idempotent dispatch behavior.
- Escalation simulation engine with consent checks, channel verification checks, idempotency replay behavior, and mock provider outcomes.
- Supabase/PostgreSQL migration contracts through `006_drop_generated_duplicate_indexes.sql`.
- OpenAPI contracts for core backend, health-device integration, and channels/calls/escalation extensions.

## Backend Work Still Left

### Persistence and Auth

- Replace stub route responses with database-backed implementations.
- Connect FastAPI to Supabase/PostgreSQL using migrations as the source of truth.
- Replace header-driven placeholder auth with the selected auth provider.
- Enforce patient access grants from persistent records.
- Persist audit logs, idempotency keys, outbox events, observations, documents, medicines, consents, risk events, escalation runs, messages, and agent tool calls.

### Agent Runtime

- Implement `AgentRuntimeAdapter` for OpenClaw prototype routing.
- Add NemoClaw deployment/profile evaluation for sandboxed production hardening.
- Build a real agent tool server with authorization, consent, idempotency, rate limits, redaction, and audit.
- Add conversation persistence, channel event routing, trace export, prompt versioning, and PHI-safe memory boundaries.

### Channels, Calls, and Automatic Communication

- Implement production provider adapters for WhatsApp Business Cloud API or BSP, Telegram Bot API, FCM/APNs push, SMS fallback, and programmable voice.
- Add webhook signature verification and receipt processing.
- Add channel account linking and verification APIs.
- Persist message dispatch attempts, call attempts, call status events, acknowledgements, retry/fallback state, and provider IDs.
- Keep emergency simulation isolated from real providers and emergency numbers.

### Health Device Backend

- Implement device catalog and compatibility checker persistence.
- Implement connector accounts, sync cursors, raw payload storage, observation normalization, quality scoring, dedupe, and outbox emission.
- Implement simulator endpoints and connect simulator runs to ingestion/risk evaluation.
- Add vendor connector framework for priority devices.

### Documents and Medical Memory

- Implement direct object-storage upload, malware scan gating, OCR, document classification, structured extraction, review/correction persistence, and source-grounded Q&A.
- Add vector index/RAG pipeline with source references and prompt-injection controls.

### Risk and Escalation

- Persist and manage patient-specific risk thresholds.
- Connect observation ingestion to risk evaluation through workers.
- Add durable escalation state machine execution, retry jobs, acknowledgement handling, and incident summary generation.
- Add clinician/compliance review workflow for high-risk threshold changes.

### Operations and Compliance

- Add CI for tests, compile checks, migration validation, and OpenAPI validation.
- Add environment configuration, secret management, logging, metrics, tracing, and provider sandbox configuration.
- Complete PHI encryption, webhook replay protection, rate limits, audit export, data deletion/export, and production readiness reviews.

## Release Impact

The backend can support contract iteration and tests today. It cannot yet support a production Flutter APK because the mobile app is not scaffolded and backend routes are not connected to durable services or real providers.
