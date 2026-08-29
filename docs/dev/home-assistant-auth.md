# Home Assistant: passwordless kiosk login

How a kio kiosk opens a Home Assistant dashboard without anyone typing a
password, why it did not work before 2026-08-28, and how to change it.

## The problem

kio can already navigate a kiosk to any `http://` or `https://` URL (the agent
calls CDP `Page.navigate`; Chromium keeps a persistent profile). HA is the
obstacle: every dashboard sits behind its login page, and a kiosk has no
keyboard.

## How it works

HA's `trusted_networks` auth provider signs a client in based on its source IP.
With `allow_bypass_login: true` and exactly one user mapped to that IP, the
login page never renders: the frontend asks `GET /auth/providers`, sees
`trusted_networks` offered, starts a login flow, and HA immediately returns an
auth code for the mapped user. Chromium then stores the refresh token in
`localStorage`, so the session also survives reboots.

The provider runs four checks (`homeassistant/auth/providers/trusted_networks.py`,
`async_validate_access`), all of which must pass:

1. `trusted_networks` is configured.
2. The client IP is inside one of the `trusted_networks`.
3. The client IP is **not** inside any HTTP `trusted_proxies`.
4. The request did not arrive over Nabu Casa cloud.

Check 3 is the one that bit us.

## Config on the HA box (`192.168.50.10`)

Two separate places hold the relevant config:

| Setting | Where it lives | How to change it |
|---|---|---|
| `homeassistant.auth_providers` | `/config/configuration.yaml` (source of truth: `private-ops/home-assistant/ha-config/configuration.yaml`) | Edit in private-ops, push, restart Core |
| `http` (`trusted_proxies`, `use_x_forwarded_for`, ...) | `/config/.storage/http` | Websocket API `http/config/configure`, then `http/config/promote` |

HA 2026.8 migrated the `http:` YAML block into `.storage/http` (the
`yaml_migration_done: true` flag). Any `http:` block left in YAML is ignored
after that migration, so `configuration.yaml` on the box no longer has one.

The auth block trusts the whole LAN. HA filters the user list by the most
specific `trusted_users` entry that matches the client, so the three kiosk
IPs resolve to exactly one user, the non-admin `Kiosk`
(`1ecac21d0753490ab61aa3fa9fb3bf78`), and `allow_bypass_login` logs them in
with no page shown. Any other LAN client gets a user picker (Alix, Eric,
Kiosk, Robbi, Guest, ...) in place of the password prompt. The k8s node IPs
sit inside the `/24` but are HTTP `trusted_proxies`, so check 3 excludes them.

```yaml
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - 192.168.50.0/24
      trusted_users:
        192.168.50.8/32:   ["1ecac21d0753490ab61aa3fa9fb3bf78"]
        192.168.50.107/32: ["1ecac21d0753490ab61aa3fa9fb3bf78"]
        192.168.50.161/32: ["1ecac21d0753490ab61aa3fa9fb3bf78"]
      allow_bypass_login: true
    - type: homeassistant
```

The stored http config:

```json
"use_x_forwarded_for": true,
"trusted_proxies": [
  "192.168.50.60/32", "192.168.50.71/32", "192.168.50.77/32", "192.168.50.79/32",
  "10.1.0.0/16"
]
```

Those are the four k8s node IPs plus the pod CIDR. `ha.squid-ink.us` is served
by the `traefik` IngressRoute in `private-ops/home-assistant/base/network.yaml`;
traefik pods reach `192.168.50.10:8123` directly, so HA sees a node IP (SNAT) or
a pod IP as the connecting address.

## What was wrong (2026-08-28)

`configuration.yaml` had carried a `trusted_networks` block for
`192.168.50.0/24` since the first private-ops commit, and `/auth/providers`
still only advertised `homeassistant`. `POST /auth/login_flow` with the
`trusted_networks` handler aborted with `not_allowed` from every LAN host.
`.storage/auth` had never recorded a single `trusted_networks` credential, so it
had never worked for anyone.

Cause: the old `http:` YAML block (now in `.storage/http`) declared
`trusted_proxies: [192.168.50.0/24]`. That made every LAN address a "proxy",
and check 3 above rejected all of them.

Fix:

1. Map the three kiosk IPs to the Kiosk user in `trusted_users` (private-ops
   `fix/ha-trusted-networks`), `scp` the file to `/config/`, `ha core check`,
   `ha core restart` (auth providers only load at startup).
2. Replace `trusted_proxies` with the node IPs + pod CIDR through the
   websocket API. HA stages this as a **pending** config and restarts itself.
   If the pending config is not promoted within five minutes it reverts to the
   old stable one on the next restart, so a broken change cannot lock you out.
3. Verify (below), then `http/config/promote`.

A backup of both files sits at
`/config/.backups/pre-trusted-networks-20260828-201532/` on the HA box.

## Driving the http config API

No websocket CLI is installed locally; a ten-line Python script does it:

```python
# hws.py <type> [json]   e.g.  hws.py http/config
import asyncio, json, sys, websockets
TOKEN = "<long-lived token from private-ops Taskfile, ha-config-push task>"
async def main():
    extra = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    async with websockets.connect("ws://192.168.50.10:8123/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        await ws.send(json.dumps({"id": 1, "type": sys.argv[1], **extra}))
        print(json.dumps(json.loads(await ws.recv()), indent=2))
asyncio.run(main())
```

Run with `uv run --with websockets python hws.py ...`.

- `http/config` — show `stable`, `pending`, `revert_at`, `active_config_type`.
- `http/config/configure` with `{"config": {...full config...}}` — stage and
  restart. The payload must carry every field (`server_port`,
  `cors_allowed_origins`, `ip_ban_enabled`, `ssl_profile`,
  `use_x_frame_options`, `login_attempts_threshold`, `use_x_forwarded_for`,
  `trusted_proxies`), not just the changed ones.
- `http/config/promote` — make pending the new stable.

## Verifying

From a kiosk (or any IP in `trusted_networks`):

```bash
# 1. The provider must be offered to this client
curl -s http://192.168.50.10:8123/auth/providers
#   -> {"providers":[{"name":"Trusted Networks","type":"trusted_networks",...}, ...]}

# 2. The login flow must finish with an auth code, not abort
curl -s -X POST http://192.168.50.10:8123/auth/login_flow \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"http://192.168.50.10:8123/","handler":["trusted_networks",null],"redirect_uri":"http://192.168.50.10:8123/?auth_callback=1"}'
#   -> {"type":"create_entry", "result":"<code>", ...}
#   before the fix: {"type":"abort","reason":"not_allowed"}
```

From a LAN host that is not a kiosk (a laptop), step 2 must return
`{"type":"form", ...}` with the user list, never `create_entry`: only the
kiosk IPs get the no-click path.

End to end: navigate a kiosk from the kio dashboard (or the HA `kio.navigate`
service) to `http://192.168.50.10:8123/lovelace/0`, then confirm on the Pi that
Chromium landed on the dashboard and not the login page:

```bash
ssh alix@192.168.50.8 'curl -s localhost:9222/json | grep -E "\"(url|title)\""'
```

Also check `ha.squid-ink.us` still loads from outside: `use_x_forwarded_for`
now only trusts the node IPs, so if traefik's traffic reached HA from some
other address HA would see the proxy's IP as the client and `ip_ban` could
start counting failed logins against it. A LAN client going out through the
public hostname is hairpin-NATed by the router and shows up in HA's logs as
`192.168.50.1`; that is normal and predates this change.

### Results, 2026-08-28

- Mac (`192.168.50.150`): `/auth/providers` lists `trusted_networks`; the
  login flow returns a `form` with the user picker, not an auto-login.
- Living Room Tv (`192.168.50.8`): lists `trusted_networks`; `login_flow`
  returns `create_entry` with an auth code.
- `https://ha.squid-ink.us/auth/providers` returns 200 through traefik.
- `POST /kiosks/<living-room-tv>/navigate` to `http://192.168.50.10:8123/lovelace/0`:
  CDP on the Pi reports `Overview – Home Assistant` at `/home/overview`, and
  `.storage/auth` holds a new refresh token for the Kiosk user with
  `last_used_ip: 192.168.50.8`.
- Pending http config promoted to stable.

## Things to know

- The kiosk IPs are DHCP-assigned by the router (Pi-hole DHCP is off). If a
  kiosk gets a new address it silently loses passwordless access; add a
  reservation or update both `trusted_networks` and `trusted_users`.
- `trusted_users` values are HA user IDs, not usernames
  (`jq '.data.users[] | {id,name}' /config/.storage/auth`).
- Use the **internal** URL on kiosks. Through `ha.squid-ink.us` HA sees the
  kiosk's IP only via `X-Forwarded-For`, which works, but adds a public
  round-trip for a LAN device.
- `kiosk-mode` v14.1.0 (NemesisRE/kiosk-mode) is installed through HACS
  (`hacs/repository/download`, repository id `497319128`); HACS registered the
  Lovelace resource `/hacsfiles/kiosk-mode/kiosk-mode.js` itself. Append
  `?kiosk` to a dashboard URL to hide the header and sidebar. Use the real
  dashboard path (`/home/overview?kiosk`): HA redirects `/lovelace/0` to it and
  drops the query string on the way. For a setting that needs no URL param,
  put `kiosk_mode: user_settings: [{users: [Kiosk], kiosk: true}]` in the
  dashboard config (private-ops `dashboards/`).
