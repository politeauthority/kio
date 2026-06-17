"""kio Pi agent package.

Controls Chromium via the Chrome DevTools Protocol and communicates with the kio
API over MQTT (commands) and HTTP (heartbeat/reporting). See ``main.py`` for the
entry point; the top-level ``agent.py`` shim simply calls into it.
"""
