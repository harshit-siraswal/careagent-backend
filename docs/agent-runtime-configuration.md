# Agent Runtime Configuration

This backend includes an agent runtime adapter boundary for Groq, OpenClaw, NemoClaw, NVIDIA-style, and custom AI provider integrations.

Implemented adapters:

- `mock`: deterministic, no-network adapter for local tests and dry-runs.
- `groq`: OpenAI-compatible Groq chat-completions adapter for in-app AI replies.

The Groq adapter keeps tool calling disabled for now (`tool_choice=none`). It can answer chat turns, but it cannot trigger calls, messages, escalation, database reads, or other side effects. Those actions must remain behind backend policy and explicit tool routes.

All provider keys must be backend environment variables. Do not place `GROQ_API_KEY` or any other provider key in Flutter, Dart defines, Vercel public variables, logs, docs, or committed files.

## Groq Target

Groq is the selected AI model provider for current in-app assistant work.

Default CareAgent settings:

- Adapter: `groq`
- Provider: `groq`
- API key env var: `GROQ_API_KEY`
- Endpoint: `https://api.groq.com/openai/v1/chat/completions`
- Default model: `llama-3.3-70b-versatile`

PowerShell local example:

```powershell
$env:AGENT_RUNTIME_ADAPTER = "groq"
$env:AGENT_RUNTIME_PROVIDER = "groq"
$env:AGENT_RUNTIME_MODEL = "llama-3.3-70b-versatile"
$env:GROQ_API_KEY = "<groq-api-key>"
python -m uvicorn app.main:app --reload
```

Use `AGENT_RUNTIME_ADAPTER=mock` when running offline tests or when no provider call should be made.

## OpenClaw Target

OpenClaw target repository: [https://github.com/openclaw/openclaw](https://github.com/openclaw/openclaw).

CareAgent should treat OpenClaw as a local-first channel/runtime gateway, not as the source of truth for PHI, consent, tool authorization, or emergency decisions. Patient data access, audit, CareAgent policy checks, consent checks, idempotency, risk evaluation, and escalation authorization must stay in the backend.

Current OpenClaw bootstrap notes:

- Runtime: Node 24 is recommended; Node 22.16+ is also supported.
- Install: `npm install -g openclaw@latest`.
- Local daemon onboarding: `openclaw onboard --install-daemon`.
- Gateway endpoint: OpenClaw can run locally on port `18789`; the default scaffold endpoint is `http://127.0.0.1:18789`.
- Channels: OpenClaw supports WhatsApp, Telegram, and many other channels. CareAgent should still route channel actions through backend authorization and audit.
- Security posture: use DM pairing for unknown senders and sandbox non-main sessions. Do not grant OpenClaw direct authority to read PHI or trigger emergency workflows without a CareAgent-authorized tool call.

## Environment Variables

Use deployment secrets, a local shell session, or a secret manager for provider keys. Do not commit real key values to git.

| Variable | Purpose |
| --- | --- |
| `AGENT_RUNTIME_ADAPTER` | Adapter implementation name. Use `groq` for Groq chat completions or `mock` for deterministic no-network mode. |
| `AGENT_RUNTIME_PROVIDER` | Provider profile: `mock`, `groq`, `openclaw`, `nemoclaw`, `nvidia`, or `custom`. |
| `AGENT_RUNTIME_MODEL` | Provider model or deployment name. |
| `AGENT_RUNTIME_ENDPOINT_URL` | Optional provider-compatible endpoint URL. |
| `AGENT_RUNTIME_PROFILE` | Optional deployment/profile name for NemoClaw or similar environments. |
| `AGENT_RUNTIME_TIMEOUT_SECONDS` | Adapter timeout budget for network adapters. |
| `AGENT_RUNTIME_API_KEY_ENV` | Name of the environment variable that contains the provider API key. |
| `GROQ_API_KEY` | Default API-key environment variable for `AGENT_RUNTIME_PROVIDER=groq`. Must exist only on the backend. |
| `NVIDIA_API_KEY` | Default API-key environment variable for `AGENT_RUNTIME_PROVIDER=nvidia`. |
| `OPENCLAW_API_KEY` | Optional API-key environment variable if an OpenClaw deployment requires one. Local OpenClaw gateway setup may not require it. |
| `NEMOCLAW_API_KEY` | Default API-key environment variable for `AGENT_RUNTIME_PROVIDER=nemoclaw`. |

PowerShell OpenClaw configuration dry-run example:

```powershell
$env:AGENT_RUNTIME_ADAPTER = "mock"
$env:AGENT_RUNTIME_PROVIDER = "openclaw"
$env:AGENT_RUNTIME_MODEL = "openclaw/default"
$env:AGENT_RUNTIME_ENDPOINT_URL = "http://127.0.0.1:18789"
```

The runtime config reports whether a key is configured as a boolean and may report the key environment variable name. It must never serialize the key value itself.
