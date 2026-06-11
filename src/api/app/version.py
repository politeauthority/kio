"""Server version helpers + the agent version/ref the server expects.

The whole repo is versioned as a unit (root VERSION + BUILD); the API image is
stamped with `KIO_VERSION` (e.g. ``0.2.0+build.4``) at build time. Agents report
the bare base (``0.2.0``, from their installed VERSION file). The server is the
authority on the "latest supported" agent version: nodes update to the git ref
matching the running server so they stay compatible with it.
"""

import os

# KIO_VERSION values that aren't a real release (local dev, unstamped images).
_NON_RELEASE = {"", "dev", "dev-latest", "unknown"}


def server_version() -> str:
    """Full server version string, e.g. ``0.2.0+build.4`` (``dev`` when unstamped)."""
    return os.environ.get("KIO_VERSION", "dev")


def agent_expected_version() -> str | None:
    """The base agent version the server expects (e.g. ``0.2.0``).

    Returns None on a non-release server (dev), so the dashboard doesn't flag every
    node as outdated when it can't make a meaningful comparison.
    """
    base = server_version().split("+", 1)[0]
    return None if base in _NON_RELEASE else base


def agent_update_ref() -> str:
    """The git ref a node should update to so it matches the running server.

    Real releases are tagged ``v<version>`` (see the ``git-tag`` task), so a server
    on ``0.2.0`` points nodes at the ``v0.2.0`` tag. A dev server points at ``main``.
    """
    base = agent_expected_version()
    return f"v{base}" if base else "main"
