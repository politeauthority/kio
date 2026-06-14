"""Agent settings: global defaults, validation bounds, and per-node overrides.

Global settings are stored in the `app_settings` table. A subset of them can be
overridden per node via a NodeMeta row keyed `settings_overrides`. The agent
fetches its *effective* settings (globals merged with its overrides) from
GET /agent/settings on boot and on a recurring checkin.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

# key -> default value
AGENT_SETTING_DEFAULTS: dict[str, int] = {
    "heartbeat_interval_seconds": 30,
    "heartbeat_jitter_seconds": 0,
    "metadata_interval_seconds": 3600,
    "settings_checkin_seconds": 300,
    "node_offline_threshold_seconds": 90,
    "event_log_purge_days": 7,
    # Display brightness (DDC/CI VCP 10). Shipped behind a gate: brightness_enabled
    # defaults to 0 (off) so the feature dark-launches and is rolled out per node or
    # fleet-wide by flipping this. brightness_default is the luminance applied when
    # the gate is enabled. Both are node-affecting + overridable so a single kiosk
    # can be enabled/tuned independently and picks the change up live (see below).
    "brightness_enabled": 0,
    "brightness_default": 80,
}

# key -> (min, max) inclusive bounds used to validate writes
SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "heartbeat_interval_seconds": (5, 3600),
    "heartbeat_jitter_seconds": (0, 300),
    "metadata_interval_seconds": (60, 86400),
    "settings_checkin_seconds": (30, 86400),
    "node_offline_threshold_seconds": (10, 3600),
    "event_log_purge_days": (1, 365),
    "brightness_enabled": (0, 1),
    "brightness_default": (0, 100),
}

# Settings a single node is allowed to override from the global default.
OVERRIDABLE_KEYS: set[str] = {
    "heartbeat_interval_seconds",
    "heartbeat_jitter_seconds",
    "metadata_interval_seconds",
    "brightness_enabled",
    "brightness_default",
}

# Settings whose change requires nodes to pull and reload. Excludes purely
# server-side settings (event_log_purge_days) so changing log retention doesn't
# bounce the whole fleet.
NODE_AFFECTING_KEYS: set[str] = {
    "heartbeat_interval_seconds",
    "heartbeat_jitter_seconds",
    "metadata_interval_seconds",
    "settings_checkin_seconds",
    "brightness_enabled",
    "brightness_default",
}

# NodeMeta key under which per-node overrides are stored.
OVERRIDES_META_KEY = "settings_overrides"


def coerce_setting(key: str, value) -> int:
    """Validate and coerce a single setting value, raising ValueError on failure."""
    if key not in AGENT_SETTING_DEFAULTS:
        raise ValueError(f"Unknown setting: {key}")
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer")
    lo, hi = SETTING_BOUNDS[key]
    if not (lo <= ivalue <= hi):
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return ivalue


async def get_global_settings(session: AsyncSession) -> dict[str, int]:
    """Return all global agent settings (stored values merged over defaults)."""
    result = await session.execute(select(AppSetting))
    stored = {r.key: r.value for r in result.scalars().all()}
    return {
        key: int(stored[key]) if key in stored and stored[key] is not None else default
        for key, default in AGENT_SETTING_DEFAULTS.items()
    }


async def update_global_settings(session: AsyncSession, updates: dict) -> dict[str, int]:
    """Validate and upsert a partial set of global settings; returns the full set."""
    for key, raw in updates.items():
        value = coerce_setting(key, raw)
        row = await session.get(AppSetting, key)
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=key, value=value))
    await session.commit()
    return await get_global_settings(session)


def effective_settings(globals_: dict[str, int], overrides: dict | None) -> dict[str, int]:
    """Merge a node's overrides (overridable keys only) over the global settings."""
    merged = dict(globals_)
    if isinstance(overrides, dict):
        for key, raw in overrides.items():
            if key not in OVERRIDABLE_KEYS:
                continue
            try:
                merged[key] = coerce_setting(key, raw)
            except ValueError:
                continue  # ignore malformed override, fall back to global
    return merged
