#!/usr/bin/env bash
# setup.sh — install the kio agent on this Raspberry Pi
# Targets Raspberry Pi OS (Raspbian-type) on a Raspberry Pi; exits early otherwise.
#
# First install (no existing config):
#   bash setup.sh                          # prompts for API URL and token
#   bash setup.sh --api-url URL --token T  # fully non-interactive
#
# Re-install / update (config already exists at /etc/kio/kiosk.conf):
#   bash setup.sh                          # reads existing config, reinstalls agent
#
# Options:
#   --env         dev or prd  (selects the stored per-env config on re-install)
#   --api-url     API URL (required on first install; no preset default is assumed)
#   --token       Node token (kio_...)
#   --start-url   Initial URL Chromium opens on boot
#   --features    Comma-separated: display_power,cec,input_switch
#   --local       Run only from manually-copied source; never pull from git.
#                 Run from inside the copied src/pi-agent/ directory.
#   --ca-cert     Install this CA into the system trust store before contacting
#                 the API (so TLS verification works on first connect)
#   --accept-cert   Trust-on-first-use: fetch the API's cert during setup, pin it
#                   to /etc/kio/api-pinned.crt, and verify against it thereafter.
#                   For private certs when no CA file is on hand.
#   --insecure-tls  Skip API TLS verification (testing only)
#   --allow-http    Pre-acknowledge an unencrypted http:// API (non-interactive
#                   runs; interactive runs are prompted to confirm instead)
#   --dns         Custom DNS server(s) for the node (e.g. a Pi-hole that resolves
#                 internal API hostnames). Comma/space separated. Prompted if a
#                 terminal is attached; KIO_DNS works too.

set -euo pipefail

# ${BASH_SOURCE[0]:-$0} so this doesn't trip `set -u` when piped via stdin
# (e.g. `curl ... | bash`), where BASH_SOURCE is unset.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
INSTALL_DIR="/opt/kio-agent"
CONFIG_FILE="/etc/kio/kiosk.yaml"
CONFIG_DIR="/etc/kio"

# ---------------------------------------------------------------------------
# OS guard — this installer targets Raspberry Pi OS (Raspbian-type)
# ---------------------------------------------------------------------------
# It uses apt and Pi-specific bits (raspi-config, i2c, HDMI cmdline, labwc), so it
# refuses to half-install on anything else. Newer Raspberry Pi OS reports ID=debian
# (not raspbian), so we key off the Pi markers + apt rather than os-release alone.
# Runs before the git bootstrap so a wrong host fails fast, without cloning.
is_raspberry_pi_os() {
  command -v apt-get >/dev/null 2>&1 || return 1
  [[ -f /etc/rpi-issue ]] && return 0
  grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null && return 0
  grep -qiE '^ID(_LIKE)?=.*raspbian' /etc/os-release 2>/dev/null && return 0
  return 1
}
if ! is_raspberry_pi_os; then
  _os="$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || echo unknown )"
  _model="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo 'non-Pi hardware')"
  echo "  ERROR: kio setup.sh targets Raspberry Pi OS (Raspbian-type) on a Raspberry Pi."
  echo "         Detected: ${_os} on ${_model}."
  echo "         Aborting to avoid a partial install on an unsupported system."
  exit 1
fi

# ---------------------------------------------------------------------------
# Self-bootstrap for `curl ... | bash`
# ---------------------------------------------------------------------------
# When piped from stdin the agent's sibling files (agent.py, scripts/, the service
# unit) aren't on disk, and interactive `read` prompts would consume the piped
# script instead of terminal input. If those files aren't beside us, clone the repo
# and re-exec setup.sh from the checkout with stdin reconnected to the terminal.
#
# --local (or KIO_NO_BOOTSTRAP=1) disables this entirely: run only from
# manually-copied source and never touch git. Detected here, before arg parsing,
# because the bootstrap check runs first.
KIO_NO_BOOTSTRAP="${KIO_NO_BOOTSTRAP:-0}"
for _a in "$@"; do
  case "$_a" in
    --local|--no-bootstrap|--no-git) KIO_NO_BOOTSTRAP=1 ;;
  esac
done

if [[ -z "${KIO_BOOTSTRAPPED:-}" && ( -z "$SCRIPT_DIR" || ! -f "$SCRIPT_DIR/agent.py" ) ]]; then
  if [[ "$KIO_NO_BOOTSTRAP" == "1" ]]; then
    echo "  ERROR: --local was given but agent.py is not next to setup.sh."
    echo "         Copy the whole src/pi-agent/ directory to the Pi and run setup.sh"
    echo "         from inside it (e.g. 'cd src/pi-agent && bash setup.sh --local ...')."
    exit 1
  fi
  KIO_REPO="${KIO_REPO:-https://github.com/politeauthority/kio.git}"
  KIO_BRANCH="${KIO_BRANCH:-main}"
  echo "  Fetching kio agent source ($KIO_REPO@$KIO_BRANCH) ..."
  if ! command -v git >/dev/null 2>&1; then
    sudo apt-get update -q && sudo apt-get install -y -q git
  fi
  _boot="$(mktemp -d)"
  git clone --depth 1 --branch "$KIO_BRANCH" "$KIO_REPO" "$_boot/kio"
  # When invoked via `sudo bash`, mktemp -d created this dir as root:root mode 700,
  # but the agent files are copied later as the kiosk user (run_as_user). Make the
  # checkout traversable/readable by everyone so that copy can read it. It holds only
  # public repo source at this point, so world-read is fine.
  chmod -R a+rX "$_boot"
  export KIO_BOOTSTRAPPED=1
  # Reconnect stdin to the terminal so prompts work after re-exec — but only if
  # /dev/tty is actually openable. It can EXIST as a device node yet fail to open
  # (ENXIO) when there's no controlling terminal, e.g. the agent self-update runs
  # this in a detached systemd-run unit; test openability, not mere presence.
  if (: </dev/tty) 2>/dev/null; then
    exec bash "$_boot/kio/src/pi-agent/setup.sh" "$@" </dev/tty
  else
    exec bash "$_boot/kio/src/pi-agent/setup.sh" "$@"
  fi
fi

# ---------------------------------------------------------------------------
# Run-as-user resolution
# ---------------------------------------------------------------------------
# setup.sh is meant to run AS THE KIOSK USER; it uses `sudo` internally for the
# steps that genuinely need root (apt, sudoers, /etc, /opt, systemd). Running the
# whole script as root (e.g. `sudo bash setup.sh`) would install uv into /root and
# chown the agent to root, breaking later deploys. We detect that case and either
# target the real user (when invoked via sudo) or refuse (bare root, no user to
# own the install).
if [[ "$(id -u)" -eq 0 ]]; then
  if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    echo "  NOTE: setup.sh is running as root via sudo. It's meant to run as the"
    echo "        kiosk user (sudo only where needed) — installing for '$SUDO_USER'."
    echo ""
  else
    echo "  ERROR: don't run setup.sh as root directly."
    echo "         Run it as the kiosk user; it will sudo for the privileged steps:"
    echo "           bash setup.sh --config <file>"
    exit 1
  fi
fi
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

# Run a command as the kiosk user (no-op wrapper when already running as them).
run_as_user() {
  if [[ "$(id -u)" -eq 0 ]]; then
    sudo -u "$TARGET_USER" -H "$@"
  else
    "$@"
  fi
}

# Ensure a path is owned by the kiosk user, repairing (recursively) and reporting
# if it has drifted — e.g. a previous run as root left root-owned files behind.
fix_owner() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  local owner
  owner="$(stat -c '%U' "$path" 2>/dev/null || echo '')"
  if [[ "$owner" != "$TARGET_USER" ]]; then
    echo "  Repairing ownership of $path ($owner -> $TARGET_USER)"
    sudo chown -R "$TARGET_USER:$TARGET_USER" "$path"
  fi
}

MQTT_HOST_DEFAULT="192.168.1.100"
MQTT_PORT_DEFAULT="1883"
# These are overridden by values from /agent/config if the API provides them

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------

ENV=""
API_URL_ARG=""
API_TOKEN_ARG=""
START_URL_ARG=""
FEATURES_ARG=""
CONFIG_FILE_ARG=""
CA_CERT_ARG=""
# Verify the API's TLS cert by default. Opt out with --insecure-tls (or
# KIO_TLS_INSECURE=1) only for testing against a self-signed API with no CA handy.
INSECURE_TLS="${KIO_TLS_INSECURE:-0}"
# --accept-cert (trust-on-first-use): fetch the API's cert during setup, pin it,
# and verify against it thereafter — for private certs where no CA file is handy.
ACCEPT_CERT="${KIO_ACCEPT_CERT:-0}"
# Pre-acknowledge an unencrypted http:// API for non-interactive runs. Interactive
# runs are prompted instead. (--insecure-tls also satisfies this.)
ALLOW_HTTP="${KIO_ALLOW_HTTP:-0}"
# Optional custom DNS server(s) for the node — e.g. a Pi-hole that resolves internal
# names like the API hostname. Comma/space separated. Interactive runs are prompted.
DNS_ARG="${KIO_DNS:-}"
CLEAR=0

while [[ $# -gt 0 ]]; do
  opt="$1"
  case "$opt" in
    --env|--api-url|--token|--start-url|--features|--config|--ca-cert|--dns)
      # Value-taking options: fail clearly if the value is missing (rather than a
      # cryptic "$2: unbound variable" under set -u).
      [[ $# -ge 2 ]] || { echo "Error: $opt requires a value"; exit 1; }
      val="$2"; shift 2
      case "$opt" in
        --env)        ENV="$val" ;;
        --api-url)    API_URL_ARG="$val" ;;
        --token)      API_TOKEN_ARG="$val" ;;
        --start-url)  START_URL_ARG="$val" ;;
        --features)   FEATURES_ARG="$val" ;;
        --config)     CONFIG_FILE_ARG="$val" ;;
        --ca-cert)    CA_CERT_ARG="$val" ;;
        --dns)        DNS_ARG="$val" ;;
      esac ;;
    --insecure-tls) INSECURE_TLS=1; shift ;;
    --accept-cert) ACCEPT_CERT=1; shift ;;
    --allow-http) ALLOW_HTTP=1; shift ;;
    # Handled early (before the git bootstrap); accept here so it isn't rejected.
    --local|--no-bootstrap|--no-git) shift ;;
    --clear) CLEAR=1; shift ;;
    *) echo "Unknown option: $opt"; exit 1 ;;
  esac
done

if [[ "$INSECURE_TLS" == "1" && "$ACCEPT_CERT" == "1" ]]; then
  echo "Error: --insecure-tls and --accept-cert are mutually exclusive"; exit 1
fi

# curl TLS posture for setup-time calls: verify by default; skip verification only
# when the operator explicitly opted into insecure TLS.
CURL_TLS_OPT=""
[[ "$INSECURE_TLS" == "1" ]] && CURL_TLS_OPT="-k"

# Install a provided CA cert into the system trust store *before* we contact the
# API, so verification works from first contact — this avoids the bootstrap
# problem where the agent would otherwise fetch certs over a connection it can't
# yet verify. (The cert is public, not secret; 644 is correct.)
if [[ -n "$CA_CERT_ARG" ]]; then
  [[ -f "$CA_CERT_ARG" ]] || { echo "  CA cert not found: $CA_CERT_ARG"; exit 1; }
  echo "  Installing CA cert into system trust store ..."
  sudo install -m 644 "$CA_CERT_ARG" /usr/local/share/ca-certificates/kio-ca.crt
  sudo update-ca-certificates >/dev/null
fi

# ---------------------------------------------------------------------------
# --clear: remove stored env config and exit
# ---------------------------------------------------------------------------

if [[ "$CLEAR" -eq 1 ]]; then
  if [[ -z "$ENV" ]]; then
    echo "Usage: bash setup.sh --env dev|prd --clear"
    exit 1
  fi
  TARGET="$CONFIG_DIR/kiosk.$ENV.yaml"
  if [[ -f "$TARGET" ]]; then
    sudo rm "$TARGET"
    echo "Cleared $ENV config ($TARGET)."
    echo "Next 'bash setup.sh --env $ENV' will prompt for a new token."
  else
    echo "No stored $ENV config found at $TARGET — nothing to clear."
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Config source: existing file or first-install prompts
# ---------------------------------------------------------------------------

KIOSK_ID=""
API_URL=""
API_TOKEN=""
MQTT_HOST=""
MQTT_PORT=""
MQTT_PREFIX=""
START_URL=""
FEATURES=""

yaml_get() {
  local key="$1"
  python3 -c "
with open('$CONFIG_FILE') as f:
    for line in f:
        stripped = line.strip()
        if stripped.startswith('${key}:'):
            print(stripped.split(':', 1)[1].strip())
            break
"
}

yaml_get_nested() {
  local section="$1" key="$2"
  python3 -c "
in_sec = False
with open('$CONFIG_FILE') as f:
    for line in f:
        if line.rstrip() == '${section}:':
            in_sec = True
        elif in_sec and line.startswith('  ${key}:'):
            print(line.split(':', 1)[1].strip())
            break
        elif in_sec and line and not line.startswith(' '):
            break
"
}

yaml_get_features() {
  python3 -c "
features = []
in_features = False
with open('$CONFIG_FILE') as f:
    for line in f:
        if line.startswith('features:'):
            val = line.split(':', 1)[1].strip()
            if val and val != '[]':
                features = [v.strip() for v in val.split(',') if v.strip()]
            in_features = True
        elif in_features and line.startswith('  - '):
            features.append(line.strip()[2:])
        elif in_features and line and not line.startswith(' '):
            break
print(','.join(features))
"
}

# If --env is given, use the per-env stored config if it exists
ENV_CONFIG=""
if [[ -n "$ENV" ]]; then
  ENV_CONFIG="$CONFIG_DIR/kiosk.$ENV.yaml"
fi

if [[ -n "$ENV_CONFIG" && -f "$ENV_CONFIG" ]]; then
  echo "  Found stored $ENV config at $ENV_CONFIG — switching."
  CONFIG_FILE="$ENV_CONFIG"
elif [[ -n "$ENV_CONFIG" ]]; then
  # --env was given but no stored config for that env — force first-install prompting
  CONFIG_FILE=""
fi

check_api_reachable() {
  local url="$1"
  echo "  Checking connectivity to $url ..."
  local http_code rc
  http_code=$(curl -s $CURL_TLS_OPT -o /dev/null -w "%{http_code}" --max-time 5 "${url}/_health" 2>/dev/null) && rc=0 || rc=$?
  if [[ "$http_code" == "200" ]]; then
    echo "  API reachable."
    return
  fi
  # curl 35/51/58/60/66/77/83 = TLS/cert trust failures: the API answered but its
  # cert isn't trusted by this Pi. Call this out specifically — otherwise the
  # operator chases a phantom outage instead of the real issue (trust must be
  # anchored before first contact; it can't be fetched over the same connection).
  case "$rc" in
    35|51|58|60|66|77|83)
      echo ""
      echo "  ERROR: ${url} is reachable but its TLS certificate is not trusted (curl exit $rc)."
      echo "  Trust has to be anchored before first contact. Re-run with one of:"
      echo "    --ca-cert /path/to/ca.crt   # internal / self-signed CA (recommended)"
      echo "    --insecure-tls              # skip verification (testing only)"
      exit 1 ;;
  esac
  echo ""
  echo "  ERROR: Could not reach ${url}/_health (got: ${http_code:-no response})"
  echo "  Check that the API is running and the URL is correct, then try again."
  exit 1
}

# Trust-on-first-use: retrieve the API's TLS cert chain now, pin it to disk, and
# point subsequent verification (setup curls + the running agent) at it. The first
# fetch is unverified — that's the TOFU tradeoff — so we print the SHA-256
# fingerprint to check out-of-band. Stored OUTSIDE /etc/kio/certs/ because the
# agent's sync_certs wipes that directory on every sync.
PINNED_CERT_DEST="/etc/kio/api-pinned.crt"
PINNED_CERT=""

pin_api_cert() {
  local url="$1"
  command -v openssl >/dev/null 2>&1 || { echo "  ERROR: openssl is required for --accept-cert"; exit 1; }
  local hostport="${url#*://}"; hostport="${hostport%%/*}"
  local host="${hostport%%:*}" port="${hostport##*:}"
  [[ "$port" == "$host" ]] && port=443
  echo "  Retrieving TLS certificate from ${host}:${port} (trust-on-first-use) ..."
  local chain
  chain=$(echo | openssl s_client -connect "${host}:${port}" -servername "$host" -showcerts 2>/dev/null \
            | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/') || true
  if [[ -z "$chain" ]]; then
    echo "  ERROR: no certificate returned from ${host}:${port} — is it serving HTTPS there?"
    exit 1
  fi
  sudo mkdir -p "$(dirname "$PINNED_CERT_DEST")"
  printf '%s\n' "$chain" | sudo tee "$PINNED_CERT_DEST" >/dev/null
  sudo chmod 644 "$PINNED_CERT_DEST"
  PINNED_CERT="$PINNED_CERT_DEST"
  # Verify the rest of setup (and the agent) against exactly what we just pinned.
  CURL_TLS_OPT="--cacert $PINNED_CERT"
  local fp
  fp=$(printf '%s\n' "$chain" | openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/^.*=//') || true
  echo "  Pinned $(grep -c 'BEGIN CERTIFICATE' <<<"$chain" || true) cert(s) -> $PINNED_CERT_DEST"
  echo "  Leaf SHA-256: ${fp:-unavailable}"
  echo "  WARNING: verify this fingerprint against your API before trusting this node."
}

# An http:// API has no transport encryption — the node token and every command
# cross the network in the clear. Accept it, but make the operator acknowledge the
# risk: prompt when there's a terminal, or require --allow-http (or --insecure-tls)
# for non-interactive runs. https:// and other schemes pass through untouched.
confirm_http_transport() {
  local url="$1"
  [[ "$url" =~ ^http:// ]] || return 0
  echo ""
  echo "  WARNING: $url uses plain HTTP — the connection to the API is NOT encrypted."
  echo "  The node token and all commands can be read or modified by anyone on the network."
  echo "  Prefer an https:// URL. Continue only on a trusted/isolated network."
  if [[ "$ALLOW_HTTP" == "1" || "$INSECURE_TLS" == "1" ]]; then
    echo "  Proceeding (--allow-http / --insecure-tls acknowledged the risk)."
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo ""
    echo "  ERROR: refusing to use an HTTP API non-interactively without acknowledgement."
    echo "  Re-run interactively to confirm, or pass --allow-http (or KIO_ALLOW_HTTP=1)."
    exit 1
  fi
  local ans=""
  read -rp "  Continue over unencrypted HTTP? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "  Aborted — use an https:// API URL, or re-run and confirm."; exit 1; }
}

# Best-effort confirmation that a DNS server is now in the active resolver set.
_verify_dns() {
  local first="${1%% *}" ok=""
  if command -v resolvectl >/dev/null 2>&1; then
    resolvectl dns 2>/dev/null | grep -qw "$first" && ok=1
  fi
  [[ -z "$ok" ]] && grep -qw "$first" /etc/resolv.conf 2>/dev/null && ok=1
  if [[ -n "$ok" ]]; then
    echo "  Verified: $first is in the active resolver set."
  else
    echo "  NOTE: couldn't confirm $first is live yet; it takes effect after reboot."
    echo "        Check later with: resolvectl dns  (or: nmcli dev show | grep IP4.DNS)"
  fi
}

# Point the node at a custom DNS server (e.g. a Pi-hole) so it can resolve internal
# names like the API hostname. Written to whatever network stack is active, in a
# location that survives reboots — and, for NetworkManager, one that also survives
# netplan regenerating the connection profiles on boot.
apply_dns() {
  local dns
  dns="$(echo "$1" | tr ',' ' ' | xargs)"   # comma/space separated -> single-spaced, trimmed
  [[ -z "$dns" ]] && return 0
  local csv="${dns// /,}"                    # comma-separated form for nmcli / conf.d
  echo "  Configuring DNS server(s): $dns"

  if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
    # Primary: a global-DNS drop-in under /etc/NetworkManager/conf.d/. netplan only
    # regenerates connection profiles (in /run) — it never touches conf.d, so this
    # survives a reboot even though the active profiles live on tmpfs. It also wins
    # over per-connection DNS.
    sudo mkdir -p /etc/NetworkManager/conf.d
    printf '# Managed by kio setup.sh\n[global-dns-domain-*]\nservers=%s\n' "$csv" \
      | sudo tee /etc/NetworkManager/conf.d/90-kio-dns.conf >/dev/null
    # Belt-and-suspenders: also set it per active connection (persisted by NM's
    # store; on Debian's netplan backend this is written back to /etc/netplan).
    local conn
    while IFS= read -r conn; do
      [[ -z "$conn" ]] && continue
      sudo nmcli con mod "$conn" ipv4.dns "$csv" ipv4.ignore-auto-dns yes 2>/dev/null || true
    done < <(nmcli -t -f NAME,DEVICE con show --active 2>/dev/null | awk -F: '$2!="lo" && $2!=""{print $1}')
    # Reload config to apply now WITHOUT bouncing links (a con up over Wi-Fi/SSH
    # could drop this very session). A full apply happens on the post-setup reboot.
    sudo nmcli general reload 2>/dev/null || true
    echo "  DNS set via NetworkManager (global conf.d drop-in + per-connection)."
    _verify_dns "$dns"
    return 0
  fi

  if systemctl is-active --quiet systemd-resolved; then
    sudo mkdir -p /etc/systemd/resolved.conf.d
    printf '[Resolve]\nDNS=%s\n' "$dns" | sudo tee /etc/systemd/resolved.conf.d/kio-dns.conf >/dev/null
    sudo systemctl restart systemd-resolved
    echo "  DNS set via systemd-resolved."
    _verify_dns "$dns"
    return 0
  fi

  if systemctl is-active --quiet dhcpcd; then
    sudo sed -i '/# kio-dns-start/,/# kio-dns-end/d' /etc/dhcpcd.conf
    { echo "# kio-dns-start"; echo "static domain_name_servers=$dns"; echo "# kio-dns-end"; } \
      | sudo tee -a /etc/dhcpcd.conf >/dev/null
    sudo systemctl restart dhcpcd
    echo "  DNS set via dhcpcd."
    _verify_dns "$dns"
    return 0
  fi

  # Last resort — may be overwritten by the network manager on reboot.
  printf 'nameserver %s\n' $dns | sudo tee /etc/resolv.conf >/dev/null
  echo "  WARNING: wrote /etc/resolv.conf directly — this may not survive a reboot."
}

# Optional custom DNS, set before contacting the API so an internal API hostname
# (e.g. *.colfax.int served by a Pi-hole) resolves. Prompted interactively; use
# --dns / KIO_DNS for automation. Blank keeps the current DNS.
if [[ -z "$DNS_ARG" && -t 0 && -z "$CONFIG_FILE_ARG" ]]; then
  echo ""
  echo "  If the API URL uses an internal hostname (e.g. *.colfax.int), this Pi needs a"
  echo "  DNS server that can resolve it — such as a Pi-hole. Leave blank to keep current DNS."
  read -rp "  Custom DNS server IP (blank to skip): " DNS_ARG
fi
[[ -n "$DNS_ARG" ]] && apply_dns "$DNS_ARG"

if [[ -n "$CONFIG_FILE_ARG" ]]; then
  # --config: read everything directly from the provided kiosk YAML — no prompts, no API fetch
  [[ ! -f "$CONFIG_FILE_ARG" ]] && echo "  Config file not found: $CONFIG_FILE_ARG" && exit 1
  CONFIG_FILE="$CONFIG_FILE_ARG"
  echo "  Loading config from $CONFIG_FILE_ARG"
  KIOSK_ID=$(yaml_get id)
  START_URL=$(yaml_get start_url)
  FEATURES=$(yaml_get_features)
  API_URL=$(yaml_get_nested api url)
  API_TOKEN=$(yaml_get_nested api token)
  MQTT_HOST=$(yaml_get_nested mqtt host)
  MQTT_PORT=$(yaml_get_nested mqtt port)
  MQTT_PREFIX=$(yaml_get_nested mqtt topic_prefix)
  # id is optional — the agent resolves its kiosk_id from the API via its token.
  [[ -z "$API_URL"   ]] && echo "  Config missing api.url"   && exit 1
  [[ -z "$API_TOKEN" ]] && echo "  Config missing api.token" && exit 1
  confirm_http_transport "$API_URL"
elif [[ -f "$CONFIG_FILE" ]] && [[ -z "$API_TOKEN_ARG" ]]; then
  echo "  Loading config from $CONFIG_FILE"
  KIOSK_ID=$(yaml_get id)
  START_URL=$(yaml_get start_url)
  FEATURES=$(yaml_get_features)
  API_URL=$(yaml_get_nested api url)
  API_TOKEN=$(yaml_get_nested api token)
  MQTT_HOST=$(yaml_get_nested mqtt host)
  MQTT_PORT=$(yaml_get_nested mqtt port)
  MQTT_PREFIX=$(yaml_get_nested mqtt topic_prefix)
  confirm_http_transport "$API_URL"
  [[ "$ACCEPT_CERT" == "1" ]] && pin_api_cert "$API_URL"
  check_api_reachable "$API_URL"
else
  # API URL is taken only from an explicit --api-url on first install; it is never
  # assumed from a built-in preset.
  [[ -n "$API_URL_ARG" ]] && API_URL="$API_URL_ARG"

  # Prompt for the API URL only when not supplied via --api-url — no default is offered.
  if [[ -z "$API_URL" ]]; then
    echo ""
    read -rp "API URL: " API_URL
  fi
  [[ -z "$API_URL" ]] && echo "API URL is required (pass --api-url or enter it when prompted)" && exit 1

  confirm_http_transport "$API_URL"
  [[ "$ACCEPT_CERT" == "1" ]] && pin_api_cert "$API_URL"
  check_api_reachable "$API_URL"

  # Prompt for token
  if [[ -n "$API_TOKEN_ARG" ]]; then
    API_TOKEN="$API_TOKEN_ARG"
  else
    echo ""
    echo "Create a node token in the dashboard at: $API_URL"
    echo ""
    read -rp "Node token (kio_...): " API_TOKEN
  fi
  [[ -z "$API_TOKEN" ]] && echo "Token is required" && exit 1

  [[ -n "$START_URL_ARG" ]] && START_URL="$START_URL_ARG"
  [[ -n "$FEATURES_ARG"  ]] && FEATURES="$FEATURES_ARG"
fi

# ---------------------------------------------------------------------------
# Fetch config from API (validates token, gets kiosk ID + MQTT settings)
# Only runs when --config was NOT used — the config file already has everything.
# ---------------------------------------------------------------------------

if [[ -z "$CONFIG_FILE_ARG" ]]; then
  echo ""
  echo "  Fetching config from $API_URL ..."

  AGENT_CONFIG=$(curl -sf $CURL_TLS_OPT \
    -H "Authorization: Bearer $API_TOKEN" \
    "${API_URL}/agent/config" 2>/dev/null) || true

  if [[ -z "$AGENT_CONFIG" ]]; then
    echo "  Failed to reach ${API_URL}/agent/config"
    echo "  Check the API URL and token, then try again."
    exit 1
  fi

  json_get() {
    echo "$AGENT_CONFIG" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1') or '')"
  }

  KIOSK_ID=$(json_get kiosk_id)
  MQTT_PREFIX=$(json_get mqtt_topic_prefix)
  API_MQTT_HOST=$(json_get mqtt_host)
  API_MQTT_PORT=$(json_get mqtt_port)
  [[ -z "$MQTT_HOST" ]] && MQTT_HOST="${API_MQTT_HOST:-$MQTT_HOST_DEFAULT}"
  [[ -z "$MQTT_PORT" ]] && MQTT_PORT="${API_MQTT_PORT:-$MQTT_PORT_DEFAULT}"

  [[ -z "$KIOSK_ID" ]] && echo "  Could not determine kiosk ID from API response" && exit 1
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "================================================"
echo "  kio agent setup"
echo "  Kiosk ID : $KIOSK_ID"
echo "  API      : $API_URL"
echo "  MQTT     : $MQTT_HOST:$MQTT_PORT ($MQTT_PREFIX)"
[[ -n "$START_URL" ]] && echo "  Start URL: $START_URL"
echo "================================================"
echo ""

# ---------------------------------------------------------------------------
# [1/5] System packages
# ---------------------------------------------------------------------------

sudo apt-get install -y -q ddcutil v4l-utils git unclutter-xfixes wlr-randr kanshi dnsutils
sudo usermod -aG i2c "$TARGET_USER"

# uv must belong to the kiosk user (the deploy/venv use $TARGET_HOME/.local/bin/uv).
UV_BIN="$TARGET_HOME/.local/bin/uv"
if [[ ! -x "$UV_BIN" ]]; then
  run_as_user bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

echo "$TARGET_USER ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /usr/bin/cec-ctl, /opt/kio-agent/update-hosts, /opt/kio-agent/update-certs, /opt/kio-agent/force-hdmi, /opt/kio-agent/set-resolution, /opt/kio-agent/self-update, /usr/bin/systemctl restart kio-agent, /bin/systemctl restart kio-agent" \
  | sudo tee /etc/sudoers.d/kio-agent > /dev/null
sudo chmod 440 /etc/sudoers.d/kio-agent

echo "[1/6] System packages installed (ddcutil, v4l-utils, unclutter-xfixes, dnsutils, i2c group, sudoers)"

# ---------------------------------------------------------------------------
# [2/5] Config
# ---------------------------------------------------------------------------

sudo mkdir -p /etc/kio
fix_owner /etc/kio
sudo mkdir -p /etc/kio/certs
fix_owner /etc/kio/certs

if [[ -n "$CONFIG_FILE_ARG" ]]; then
  cp "$CONFIG_FILE_ARG" /etc/kio/kiosk.yaml
else
  # Verify TLS by default (agent treats a missing tls_verify as true).
  #   --insecure-tls  -> tls_verify: false  (no verification)
  #   --accept-cert   -> tls_verify: <pinned cert path>  (verify against it)
  TLS_VERIFY_LINE=""
  if [[ "$INSECURE_TLS" == "1" ]]; then
    TLS_VERIFY_LINE=$'\n  tls_verify: false'
  elif [[ -n "$PINNED_CERT" ]]; then
    TLS_VERIFY_LINE=$'\n  tls_verify: '"$PINNED_CERT"
  fi

  FEATURES_YAML=""
  if [[ -n "$FEATURES" ]]; then
    FEATURES_YAML=$(echo "$FEATURES" | tr ',' '\n' | sed 's/^[[:space:]]*//' | grep -v '^$' | sed 's/^/  - /')
    FEATURES_YAML=$'\nfeatures:\n'"$FEATURES_YAML"
  fi

  # No 'id:' — the node's identity is its token; the agent resolves its kiosk_id
  # from the API at startup (GET /agent/config) and keeps it for the run.
  tee /etc/kio/kiosk.yaml > /dev/null <<EOF
start_url: $START_URL$FEATURES_YAML

api:
  url: $API_URL
  token: $API_TOKEN$TLS_VERIFY_LINE

mqtt:
  host: $MQTT_HOST
  port: $MQTT_PORT
  topic_prefix: $MQTT_PREFIX
EOF
fi

# The config holds the API bearer token in plaintext — keep it readable only by
# the agent's user (the kio-agent service runs as $TARGET_USER).
sudo chown "$TARGET_USER:$TARGET_USER" /etc/kio/kiosk.yaml
sudo chmod 600 /etc/kio/kiosk.yaml

# Create via sudo and hand ownership to the kiosk user, so this works whether the
# file is missing, already owned by the user, or left root-owned by an earlier run
# (e.g. a botched `sudo bash setup.sh`). The agent (running as the user) writes here.
sudo touch /etc/kio/browser-flags
sudo chown "$TARGET_USER:$TARGET_USER" /etc/kio/browser-flags

# Block Chromium permission prompts outright. The kiosks have no keyboard, so a
# "site wants to show notifications" popup can never be dismissed and just sits
# over the content. A managed policy with the default content setting at 2
# (block) denies silently and stops Chromium from ever showing the prompt — and,
# being a managed policy, it can't be re-enabled from the UI. Geolocation is the
# other unprompted-popup of the same class, so block it too. Written to both the
# `chromium` and `chromium-browser` policy paths so it applies regardless of
# which package the image ships.
for _pol_dir in /etc/chromium/policies/managed /etc/chromium-browser/policies/managed; do
  sudo mkdir -p "$_pol_dir"
  printf '{\n  "DefaultNotificationsSetting": 2,\n  "DefaultGeolocationSetting": 2\n}\n' \
    | sudo tee "$_pol_dir/kio-permissions.json" >/dev/null
done
echo "  Chromium notification/geolocation prompts blocked via managed policy"

# Ensure HDMI is always active even when the display is off at boot.
# hdmi_force_hotplug makes the firmware always assert HPD so the Pi outputs a signal.
# With vc4-kms-v3d + disable_fw_kms_setup=1 (Raspberry Pi OS default), the kernel DRM
# driver also needs an explicit video= param — otherwise it sees no EDID and marks the
# connector disconnected, preventing ddcutil and CEC from working.
BOOT_CONFIG="/boot/firmware/config.txt"
[[ ! -f "$BOOT_CONFIG" ]] && BOOT_CONFIG="/boot/config.txt"
if [[ -f "$BOOT_CONFIG" ]] && ! grep -q "hdmi_force_hotplug=1" "$BOOT_CONFIG"; then
  echo "hdmi_force_hotplug=1" | sudo tee -a "$BOOT_CONFIG" > /dev/null
  echo "  Added hdmi_force_hotplug=1 to $BOOT_CONFIG"
fi

CMDLINE="/boot/firmware/cmdline.txt"
[[ ! -f "$CMDLINE" ]] && CMDLINE="/boot/cmdline.txt"
if [[ -f "$CMDLINE" ]] && ! grep -q "video=HDMI-A-1:" "$CMDLINE"; then
  sudo sed -i 's/$/ video=HDMI-A-1:1920x1080@60/' "$CMDLINE"
  echo "  Added video=HDMI-A-1:1920x1080@60 to $CMDLINE (forces KMS to enable HDMI output)"
fi

# Save env-specific config so future --env switches don't need prompting
if [[ -n "$ENV" ]]; then
  sudo cp /etc/kio/kiosk.yaml "$CONFIG_DIR/kiosk.$ENV.yaml"
fi

echo "[2/6] Config written to /etc/kio/kiosk.yaml"

# ---------------------------------------------------------------------------
# [3/5] Agent
# ---------------------------------------------------------------------------

sudo mkdir -p "$INSTALL_DIR"
# Repair drifted ownership (e.g. a prior run as root left root-owned files/venv),
# then do all file ops AS THE KIOSK USER so nothing ends up owned by root.
fix_owner "$INSTALL_DIR"
run_as_user cp "$SCRIPT_DIR/agent.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/scripts/update-hosts" "$SCRIPT_DIR/scripts/update-certs" "$SCRIPT_DIR/scripts/browser-start" "$SCRIPT_DIR/scripts/force-hdmi" "$SCRIPT_DIR/scripts/set-resolution" "$SCRIPT_DIR/scripts/self-update" "$INSTALL_DIR/"
run_as_user chmod +x "$INSTALL_DIR/update-hosts" "$INSTALL_DIR/update-certs" "$INSTALL_DIR/browser-start" "$INSTALL_DIR/force-hdmi" "$INSTALL_DIR/set-resolution" "$INSTALL_DIR/self-update"
[[ -f "$SCRIPT_DIR/VERSION" ]] && run_as_user cp "$SCRIPT_DIR/VERSION" "$INSTALL_DIR/"
run_as_user rm -rf "$INSTALL_DIR/venv"
run_as_user "$UV_BIN" venv --seed "$INSTALL_DIR/venv"
run_as_user "$UV_BIN" pip install --quiet --python "$INSTALL_DIR/venv/bin/python" -r "$INSTALL_DIR/requirements.txt"
# Belt-and-suspenders: guarantee the whole tree is kiosk-user-owned afterward.
fix_owner "$INSTALL_DIR"
echo "[3/6] Agent installed to $INSTALL_DIR"

# ---------------------------------------------------------------------------
# [4/6] Systemd service
# ---------------------------------------------------------------------------

# HDMI is forced on via the force-hdmi script, run as ExecStartPre in the unit
# below (writes to /sys/kernel/debug/dri/gpu/HDMI-A-*/force). This drives HDMI
# output even if the TV was off at boot and asserted no HPD, so ddcutil/CEC can
# reach the display once it powers on. See scripts/force-hdmi.
sed "s/^User=.*/User=$TARGET_USER/" "$SCRIPT_DIR/kio-agent.service" \
  | sudo tee /etc/systemd/system/kio-agent.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable kio-agent.service
sudo systemctl restart kio-agent.service
echo "[4/6] Systemd service installed, enabled, and started"

# ---------------------------------------------------------------------------
# [5/6] Graphical session autostart (labwc)
# ---------------------------------------------------------------------------

run_as_user mkdir -p "$TARGET_HOME/.config/labwc"
run_as_user mkdir -p "$TARGET_HOME/.config/kanshi"
# kanshi applies the agent-written display profile (~/.config/kanshi/config) on
# session start and every display reconnect — the durable resolution persistence path.
# `pkill -x kanshi` first so we end up with exactly one instance even when the base
# image's /etc/xdg/labwc/autostart already started one (this user autostart runs after it).
run_as_user bash -c "printf 'pkill wf-panel-pi\npkill -x kanshi\nkanshi &\nunclutter-xfixes --timeout 1 &\n%s/browser-start\n' '$INSTALL_DIR' > '$TARGET_HOME/.config/labwc/autostart'"
run_as_user chmod +x "$TARGET_HOME/.config/labwc/autostart"
echo "[5/6] labwc autostart configured"

# ---------------------------------------------------------------------------
# [6/6] Auto-login
# ---------------------------------------------------------------------------

if command -v raspi-config &>/dev/null; then
  sudo raspi-config nonint do_boot_behaviour B4 2>/dev/null || true
fi
echo "[6/6] Auto-login configured"

echo ""
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  Agent is running. Watch logs:"
echo "    journalctl -fu kio-agent"
echo ""
echo "  Reboot required to apply:"
echo "    - video=HDMI-A-1 cmdline (forces KMS DRM to enable HDMI output)"
echo "    - hdmi_force_hotplug (asserts HPD so Pi always drives HDMI signal)"
echo "    - i2c group change (display power / input switching via ddcutil)"
echo ""
echo "    sudo reboot"
echo ""
echo "  After reboot, run 'Detect Hardware' from the dashboard"
echo "  to probe and save the available features for this node."
echo "================================================"
echo ""
