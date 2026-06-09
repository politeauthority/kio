# Docs

## Features

| | |
|---|---|
| [Onboarding a kiosk](features/onboarding-a-kiosk.md) | Add a new Pi from fresh OS install to online in the dashboard |

## Operations

| | |
|---|---|
| [Production deployment](production.md) | Kubernetes architecture, namespaces, and deploy process |
| [Authentication](security/authentication.md) | Dashboard auth, agent tokens, and API keys |

## Development

| | |
|---|---|
| [API & UI development](dev/api-ui-development.md) | Running the FastAPI backend and Vue frontend locally |
| [Agent development](dev/agent-development.md) | Working on the Pi agent, config files, and deploying to nodes |
| [Agent debugging](dev/agent-debug.md) | SSH into a node, read logs, and diagnose agent issues |
| [Feature flags](dev/feature-flags.md) | How runtime UI feature flags are implemented, used, and added |
| [Event logs](dev/event-logs.md) | The `command_logs` audit trail, search API, and how events get written |
| [Releasing](dev/releasing.md) | Versioning, building and pushing images, cutting a release |
| [Staging](dev/staging.md) | Deploying branches to the `kio-stg` namespace for testing |
| [Testing](dev/testing.md) | Unit tests and e2e regression tests against a live environment |
| [Home Assistant](dev/home-assistant.md) | The kio HA integration and how to develop against it |

## Research

| | |
|---|---|
| [HDMI CEC](research/hdmi-cec.md) | CEC support on the Dell S2721QS display via kio-2 |
| [Custom DNS & certs](research/custom-dns-and-certs.md) | Local DNS entries and TLS certificates on Pi nodes |
| [Home Assistant integration plan](research/home-assistant-integration.md) | Notes on publishing a HACS-compatible integration |

## Notes

| | |
|---|---|
| [kio-2 change log](kio-2-changes.md) | Running log of hardware and config changes on kio-2 |
