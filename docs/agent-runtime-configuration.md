# Agent Runtime Configuration

This backend includes an initial agent runtime adapter scaffold for OpenClaw, NemoClaw, NVIDIA-style, and custom AI provider integrations.

The only implemented adapter is `mock`. It is deterministic and does not make network calls. Real provider adapters should implement `AgentRuntimeAdapter` in `app.agent.runtime` and must preserve the same secret-redaction behavior.

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
| `AGENT_RUNTIME_ADAPTER` | Adapter implementation name. Use `mock` until a real provider adapter is implemented. |
| `AGENT_RUNTIME_PROVIDER` | Provider profile: `mock`, `openclaw`, `nemoclaw`, `nvidia`, or `custom`. |
| `AGENT_RUNTIME_MODEL` | Provider model or deployment name. |
| `AGENT_RUNTIME_ENDPOINT_URL` | Optional provider-compatible endpoint URL. |
| `AGENT_RUNTIME_PROFILE` | Optional deployment/profile name for NemoClaw or similar environments. |
| `AGENT_RUNTIME_TIMEOUT_SECONDS` | Adapter timeout budget for future network adapters. |
| `AGENT_RUNTIME_API_KEY_ENV` | Name of the environment variable that contains the provider API key. |
| `NVIDIA_API_KEY` | Default API-key environment variable for `AGENT_RUNTIME_PROVIDER=nvidia`. |
| `OPENCLAW_API_KEY` | Optional API-key environment variable if an OpenClaw deployment requires one. Local OpenClaw gateway setup may not require it. |
| `NEMOCLAW_API_KEY` | Default API-key environment variable for `AGENT_RUNTIME_PROVIDER=nemoclaw`. |

PowerShell dry-run example:

```powershell
$env:AGENT_RUNTIME_ADAPTER = "mock"
$env:AGENT_RUNTIME_PROVIDER = "openclaw"
$env:AGENT_RUNTIME_MODEL = "openclaw/default"
$env:AGENT_RUNTIME_ENDPOINT_URL = "http://127.0.0.1:18789"
```

The runtime config reports whether a key is configured as a boolean and may report the key environment variable name. It must never serialize the key value itself.
