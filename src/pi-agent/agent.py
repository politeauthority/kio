#!/usr/bin/env python3
"""kio Pi agent entry point.

A thin shim kept at the install root (e.g. /opt/kio-agent/agent.py) so the systemd
unit and deploy scripts can keep launching ``agent.py`` unchanged. All logic lives
in the :mod:`kio_agent` package alongside this file.
"""

from kio_agent.main import main

if __name__ == "__main__":
    main()
