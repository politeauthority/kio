import asyncio
import json
import logging
from collections import defaultdict

import paho.mqtt.client as mqtt

from app.config import settings

logger = logging.getLogger("kio.mqtt")

_client: mqtt.Client | None = None
_loop: asyncio.AbstractEventLoop | None = None
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
_heartbeat_callback = None


def _prefix() -> str:
    return settings.mqtt_topic_prefix


def subscribe(kiosk_id: str, queue: asyncio.Queue) -> None:
    _subscribers[kiosk_id].append(queue)


def unsubscribe(kiosk_id: str, queue: asyncio.Queue) -> None:
    try:
        _subscribers[kiosk_id].remove(queue)
    except ValueError:
        pass


def notify_subscribers(kiosk_id: str, payload: dict) -> None:
    for q in list(_subscribers.get(kiosk_id, [])):
        if _loop is not None:
            _loop.call_soon_threadsafe(q.put_nowait, payload)


def publish_command(kiosk_id: str, payload: dict) -> None:
    if _client is None:
        raise RuntimeError("MQTT client not initialized")
    topic = f"{_prefix()}/kiosks/{kiosk_id}/command"
    _client.publish(topic, json.dumps(payload), qos=1)
    logger.info("Published to %s: %s", topic, payload)


def publish_nav(kiosk_id: str, url: str, command_id: str | None = None) -> None:
    if _client is None:
        raise RuntimeError("MQTT client not initialized")
    topic = f"{_prefix()}/kiosks/{kiosk_id}/nav"
    payload = {"url": url}
    if command_id:
        payload["command_id"] = command_id
    _client.publish(topic, json.dumps(payload), qos=1)
    logger.info("Published to %s: %s", topic, url)


def _on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code != 0:
        logger.error("MQTT connect failed: %s", reason_code)
        return
    logger.info("MQTT connected to %s:%s (prefix: %s)", settings.mqtt_host, settings.mqtt_port, _prefix())


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties) -> None:
    logger.warning("MQTT disconnected (rc=%s)", reason_code)


def start_mqtt(loop: asyncio.AbstractEventLoop, heartbeat_callback) -> None:
    global _client, _loop, _heartbeat_callback
    _loop = loop
    _heartbeat_callback = heartbeat_callback

    _client = mqtt.Client(
        client_id=f"kio-api-{_prefix().replace('/', '-')}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    _client.on_connect = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.connect_async(settings.mqtt_host, settings.mqtt_port)
    _client.loop_start()
    logger.info("MQTT client started (%s:%s)", settings.mqtt_host, settings.mqtt_port)


def stop_mqtt() -> None:
    if _client:
        _client.loop_stop()
        _client.disconnect()
    logger.info("MQTT client stopped")
