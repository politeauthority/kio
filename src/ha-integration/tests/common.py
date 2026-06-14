"""Test helpers shared across the kio integration test modules."""


def make_kiosk(**overrides) -> dict:
    """A kiosk dict shaped like the kio API's GET /kiosks payload."""
    kiosk = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Lobby",
        "hostname": "kio-lobby",
        "current_url": "https://example.com/dash",
        "status": "online",
        "last_seen": "2026-06-13T12:00:00+00:00",
        "features": [],
        "device_type": "Raspberry Pi 4",
        "ip_address": "192.168.1.50",
        "current_input": "hdmi1",
        "display_on": True,
        "agent_version": "0.5.0",
        "uptime_seconds": 3600,
        "uptime_reported_at": "2026-06-13T12:00:00+00:00",
        "playlist_id": None,
        "meta": {},
        "browser_flags": [],
        "browser_tabs": [],
        "playlist_state": None,
        "tab_cycle_state": None,
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-13T12:00:00+00:00",
    }
    kiosk.update(overrides)
    return kiosk
