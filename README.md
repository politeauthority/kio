# kio

kio is a self-hosted kiosk management platform for Raspberry Pi nodes. A central dashboard lets you monitor every kiosk in real time, push URL navigation, manage browser tabs, control display power, and switch HDMI inputs — all without touching the physical hardware.

## How it works

Each Pi runs a lightweight agent that connects to the central API over MQTT and HTTP. The agent controls Chromium via the Chrome DevTools Protocol and reports status back on a heartbeat. The dashboard streams live updates to the browser over SSE.

```
[Vue 3 dashboard] ──REST/SSE──▶ [FastAPI] ──SQLAlchemy──▶ [PostgreSQL]
                                     │
                                Paho MQTT
                                     │
                          [Eclipse Mosquitto broker]
                                     │
                          [Pi agent (Raspberry Pi)]
                                     │
                              CDP / WebSocket
                                     │
                            [Chromium :9222]
```

## Docs

| | |
|---|---|
| [Onboarding a kiosk](docs/features/onboarding-a-kiosk.md) | Add a new Pi from fresh OS install to online in the dashboard |
| [Production deployment](docs/production.md) | Kubernetes architecture, namespaces, and deploy process |
| [Authentication](docs/security/authentication.md) | Dashboard auth, agent tokens, and API keys |
| [API & UI development](docs/dev/api-ui-development.md) | Running the API and frontend locally |
| [Agent development](docs/dev/agent-development.md) | Working on the Pi agent and deploying to nodes |
| [Releasing](docs/dev/releasing.md) | Versioning, building images, and cutting a release |
| [Staging](docs/dev/staging.md) | Using the `kio-stg` environment to test branches |
| [Testing](docs/dev/testing.md) | Unit tests and e2e regression tests |

→ [All docs](docs/index.md)
