"""MQTT
"""
import json
import logging
import os

import paho.mqtt.client as mqtt


BROKER_ADDRESS = os.environ.get('KIO_SERVER_MQTT_HOST')
MQTT_TOPIC = os.environ.get('KIO_SERVER_MQTT_TOPIC')


def publish(payload: dict) -> bool:
    """ """
    client = mqtt.Client('kio-server')
    client.connect(BROKER_ADDRESS, keepalive=60)
    client.publish(MQTT_TOPIC, payload=json.dumps(payload), retain=False)
    logging.info('Published message')
    return True


# End File: kio/kio-server/mqtt_handler.py
