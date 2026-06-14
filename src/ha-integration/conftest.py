"""Shared fixtures for the kio HA integration tests.

custom_components/ sits next to this file, so it is importable as
`custom_components.kio` once pytest puts this directory on sys.path.
"""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow HA to load the custom `kio` integration during tests."""
    yield
