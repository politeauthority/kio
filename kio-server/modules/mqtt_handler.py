"""MQTT
"""
import json
import logging
import os

import paho.mqtt.client as mqtt


BROKER_ADDRESS = os.environ.get('KIO_SERVER_MQTT_HOST')


def publish(payload: dict):
    client = mqtt.Client('kio-server')
    client.connect(BROKER_ADDRESS, keepalive=60)
    client.publish('kio', payload=json.dumps(payload), retain=False)
    logging.info('Published message')


# End File: kio/kio-server/mqtt_handler.py
