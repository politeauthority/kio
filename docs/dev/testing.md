# Testing

Kio has two layers of tests: unit tests that run locally against mocked dependencies, and end-to-end regression tests that run against a live Kubernetes environment.

## Unit tests (`src/api/tests/`)

Fast, in-process tests for the FastAPI application. The database and MQTT broker are mocked — no external services required.

**Run:**
```bash
cd src/api
uv run pytest
```

**Stack:** `pytest` + `pytest-asyncio` + `httpx.AsyncClient` with `ASGITransport`. The test app is built without the lifespan (no MQTT startup), and the DB session is replaced with a `MagicMock` that returns controllable results.

**Key files:**

| File | What it covers |
|------|---------------|
| `tests/conftest.py` | `client` fixture (dashboard, auth bypassed), `agent_client` fixture (Pi agent auth), `make_kiosk()` helper |
| `tests/test_auth.py` | JWT generation, expiry, wrong secret, bearer + query-param paths |
| `tests/test_agent_router.py` | `/agent/heartbeat`, `/agent/config`, `/agent/browser-flags`, `/agent/meta`, `/agent/command-log` |
| `tests/test_kiosks_router.py` | CRUD, commands, navigate, browser tab endpoints, command log, meta, playlists |
| `tests/test_kiosk_service.py` | Service-layer logic (no HTTP) |
| `tests/test_playlists_router.py` | Playlist CRUD and item management |

When adding a new model field or endpoint, update `make_kiosk()` in `conftest.py` if `KioskRead` serialization is affected — missing fields cause `ResponseValidationError` at test time.

---

## End-to-end tests (`tests/e2e/`)

Regression tests that hit a real running environment. API tests use `httpx`; UI tests use Playwright (headless Chromium).

### Setup (once per machine)

```bash
task test:e2e:install
```

This runs `uv sync` inside `tests/e2e/` and downloads the Chromium browser binary.

### Configuration

Copy the example env file and fill in credentials:

```bash
cp tests/e2e/.env.example tests/e2e/.env
```

```
KIO_API_URL=http://api.kio-dev.example.local   # or stg / prd
KIO_UI_URL=http://kio-dev.example.local
KIO_USERNAME=<your username>
KIO_PASSWORD=<your password>
```

The `.env` file is gitignored. Variables can also be passed directly on the command line.

### Running

```bash
task test:e2e          # API + UI (sequential)
task test:e2e:api      # API only
task test:e2e:ui       # UI only (Playwright)
```

Pass extra pytest flags via `CLI_ARGS`:
```bash
task test:e2e:api -- -k test_auth
task test:e2e:ui -- --headed          # watch the browser
task test:e2e:ui -- --slowmo=500      # slow down for debugging
```

### What the tests cover

**API (`tests/e2e/api/`)**

| File | Coverage |
|------|----------|
| `test_health.py` | `GET /_health` |
| `test_auth.py` | Login, bad credentials → 401, unauthenticated request → 401 |
| `test_kiosks.py` | CRUD, send command, navigate, command log |
| `test_browsers.py` | All browser tab endpoints; 404 on missing kiosk |

Each test that mutates state creates an isolated `e2e-<random>` kiosk via the `test_kiosk` fixture and deletes it in teardown — safe to run against dev or staging.

**UI (`tests/e2e/ui/`)**

| File | Coverage |
|------|----------|
| `test_login.py` | Page loads, error on bad credentials, redirect on success |
| `test_kiosk_list.py` | Heading, Add Kiosk modal, row click navigates to detail |
| `test_kiosk_detail.py` | Name/status/cards visible, Browsers card with Open tab form, back link |

Detail and list tests that depend on a kiosk existing in the environment skip gracefully rather than failing when the environment is empty.

### Targeting a different environment

```bash
KIO_API_URL=http://api.stg.kio.example.local \
KIO_UI_URL=http://stg.kio.example.local \
task test:e2e
```

Or set the values in `tests/e2e/.env` before running. See [staging.md](staging.md) for how to deploy a branch to the staging environment first.
