"""Mutable runtime state shared across the agent.

These are deliberately module-level globals: the original single-file agent kept
them as globals, and several helpers (reporting, command handling) read them at
call time. Other modules reference them as ``runtime.TLS_VERIFY`` and
``runtime.agent`` so they always observe the current value after :func:`main`
wires everything up.

``AGENT_VERSION`` and ``BOOT_ID`` are resolved once at import and never change,
so they may be imported by value.
"""

from __future__ import annotations

import os
import typing

from kio_agent.constants import _SYSTEM_CA_BUNDLE

if typing.TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from kio_agent.agent import KioAgent


def _read_version() -> str:
    """Read the agent VERSION file, which sits at the install root one directory
    above this package (e.g. /opt/kio-agent/VERSION). Returns 'unknown' if absent."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(root, "VERSION")).read().strip()
    except Exception:
        return "unknown"


def _read_boot_id() -> str:
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip()
    except Exception:
        return "unknown"


AGENT_VERSION = _read_version()
BOOT_ID = _read_boot_id()

# Resolved from config at startup; passed straight to requests' verify= (a bool,
# or a path to a CA bundle). Mutated once, in main().
TLS_VERIFY: "bool | str" = True

# The live agent instance, set by main(). Read by reporting and command helpers.
agent: "KioAgent | None" = None


def resolve_tls_verify(value: "bool | str") -> "bool | str":
    """Map config's tls_verify into a value for requests' verify= argument.

    - false / "false" / "0" / "no" / "off" -> False  (no verification; insecure)
    - any other string                      -> that path, used as a CA bundle (pinning)
    - true (the default)                    -> the system CA store if present, else
                                               certifi (returns True)
    """
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("false", "0", "no", "off"):
            return False
        if low not in ("true", "1", "yes", "on", ""):
            return value  # explicit CA bundle path
        value = True
    if not value:
        return False
    return _SYSTEM_CA_BUNDLE if os.path.exists(_SYSTEM_CA_BUNDLE) else True
