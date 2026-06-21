"""Make the pi-agent source importable from these tests.

The agent isn't installed as a distribution during testing, so put its source
directory (which contains the ``kio_agent`` package) on sys.path. Done here rather
than via pytest's ``pythonpath`` so the tests import correctly no matter which
directory pytest is invoked from.
"""

import os
import sys

_PI_AGENT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi-agent"))
if _PI_AGENT_SRC not in sys.path:
    sys.path.insert(0, _PI_AGENT_SRC)
