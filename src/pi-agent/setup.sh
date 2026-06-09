#!/usr/bin/env bash
# setup.sh — install the kio agent on this Raspberry Pi
#
# First install (no existing config):
#   bash setup.sh                          # prompts for API URL and token
#   bash setup.sh --env dev                # uses dev API URL, prompts for token
#   bash setup.sh --env prd               # uses prod API URL, prompts for token
#   bash setup.sh --api-url URL --token T  # fully non-interactive
#
# Re-install / update (config already exists at /etc/kio/kiosk.conf):
#   bash setup.sh                          # reads existing config, reinstalls agent
#
# Options:
#   --env         dev or prd  (sets API URL from preset)
#   --api-url     Override API URL
#   --token       Node token (kio_...)
#   --start-url   Initial URL Chromium opens on boot
#   --features    Comma-separated: display_power,cec,input_switch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# When invoked via `curl | bash`, there is no agent.py alongside this script.
# Fetch the full source tree from GitHub and re-exec from the real path.
KIO_GITHUB_BRANCH="bootstrap"
KIO_GITHUB_REPO="https://github.com/politeauthority/kio"

if [[ ! -f "$SCRIPT_DIR/agent.py" ]]; then
  FETCH_DIR="$(mktemp -d)"
  echo "Fetching kio agent (branch: $KIO_GITHUB_BRANCH)..."
  curl -fsSL "${KIO_GITHUB_REPO}/archive/refs/heads/${KIO_GITHUB_BRANCH}.tar.gz" \
    | tar -xz -C "$FETCH_DIR" --strip-components=1
  [[ -f "$FETCH_DIR/VERSION" ]] && cp "$FETCH_DIR/VERSION" "$FETCH_DIR/src/pi-agent/"
  exec bash "$FETCH_DIR/src/pi-agent/setup.sh" "$@" </dev/tty
fi

INSTALL_DIR="/opt/kio-agent"
CONFIG_FILE="/etc/kio/kiosk.yaml"
CONFIG_DIR="/etc/kio"

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

DEV_API_URL="http://kio-dev.example.local"
PRD_API_URL="https://api.kio.example.local"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------

ENV=""
API_URL_ARG=""
API_TOKEN_ARG=""
START_URL_ARG=""
FEATURES_ARG=""
CONFIG_FILE_ARG=""
CLEAR=0

while [[ $# -gt 0 ]]; do
  opt="$1"
  case "$opt" in
    --env|--api-url|--token|--start-url|--features|--config)
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
      esac ;;
    --clear) CLEAR=1; shift ;;
    *) echo "Unknown option: $opt"; exit 1 ;;
  esac
done

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
  local http_code
  http_code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "${url}/_health" 2>/dev/null) || true
  if [[ "$http_code" == "200" ]]; then
    echo "  API reachable."
  else
    echo ""
    echo "  ERROR: Could not reach ${url}/_health (got: ${http_code:-no response})"
    echo "  Check that the API is running and the URL is correct, then try again."
    exit 1
  fi
}

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
  check_api_reachable "$API_URL"
else
  # Determine default API URL from --env or --api-url
  DEFAULT_URL=""
  if [[ -n "$API_URL_ARG" ]]; then
    DEFAULT_URL="$API_URL_ARG"
  elif [[ "$ENV" == "dev" ]]; then
    DEFAULT_URL="$DEV_API_URL"
  elif [[ "$ENV" == "prd" ]]; then
    DEFAULT_URL="$PRD_API_URL"
  fi

  # Always prompt for API URL, showing the default if one exists
  echo ""
  if [[ -n "$DEFAULT_URL" ]]; then
    read -rp "API URL [$DEFAULT_URL]: " API_URL
    [[ -z "$API_URL" ]] && API_URL="$DEFAULT_URL"
  else
    read -rp "API URL: " API_URL
  fi
  [[ -z "$API_URL" ]] && echo "API URL is required" && exit 1

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

  AGENT_CONFIG=$(curl -skf \
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
  MQTT_HOST=$(json_get mqtt_host)
  MQTT_PORT=$(json_get mqtt_port)
  [[ -z "$MQTT_HOST" ]] && echo "  API did not return MQTT host — check server configuration" && exit 1
  [[ -z "$MQTT_PORT" ]] && echo "  API did not return MQTT port — check server configuration" && exit 1

  MQTT_PREFIX_DEFAULT=$(json_get mqtt_topic_prefix)
  echo ""
  read -rp "MQTT topic prefix [${MQTT_PREFIX_DEFAULT}]: " _prefix
  MQTT_PREFIX="${_prefix:-$MQTT_PREFIX_DEFAULT}"
  [[ -z "$MQTT_PREFIX" ]] && echo "MQTT topic prefix is required" && exit 1

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

sudo apt-get install -y -q ddcutil v4l-utils git unclutter-xfixes
sudo usermod -aG i2c "$TARGET_USER"

# uv must belong to the kiosk user (the deploy/venv use $TARGET_HOME/.local/bin/uv).
UV_BIN="$TARGET_HOME/.local/bin/uv"
if [[ ! -x "$UV_BIN" ]]; then
  run_as_user bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

echo "$TARGET_USER ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /usr/bin/cec-ctl, /opt/kio-agent/update-hosts, /opt/kio-agent/force-hdmi, /usr/bin/systemctl restart kio-agent, /bin/systemctl restart kio-agent" \
  | sudo tee /etc/sudoers.d/kio-agent > /dev/null
sudo chmod 440 /etc/sudoers.d/kio-agent

echo "[1/6] System packages installed (ddcutil, v4l-utils, unclutter-xfixes, i2c group, sudoers)"

# ---------------------------------------------------------------------------
# [2/5] Config
# ---------------------------------------------------------------------------

sudo mkdir -p /etc/kio
fix_owner /etc/kio

if [[ -n "$CONFIG_FILE_ARG" ]]; then
  cp "$CONFIG_FILE_ARG" /etc/kio/kiosk.yaml
else
  TLS_VERIFY_LINE=""
  [[ "$ENV" == "prd" ]] && TLS_VERIFY_LINE=$'\n  tls_verify: false'

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

touch /etc/kio/browser-flags

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
run_as_user cp "$SCRIPT_DIR/agent.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/scripts/update-hosts" "$SCRIPT_DIR/scripts/browser-start" "$SCRIPT_DIR/scripts/force-hdmi" "$INSTALL_DIR/"
run_as_user chmod +x "$INSTALL_DIR/update-hosts" "$INSTALL_DIR/browser-start" "$INSTALL_DIR/force-hdmi"
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
run_as_user bash -c "printf 'pkill wf-panel-pi\nunclutter-xfixes --timeout 1 &\n%s/browser-start\n' '$INSTALL_DIR' > '$TARGET_HOME/.config/labwc/autostart'"
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
