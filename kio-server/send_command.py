import json
import os
import requests
import random
import sys

import paho.mqtt.client as mqtt

MQTT_TOPIC = os.environ.get('KIO_SERVER_MQTT_TOPIC')
BROKER_ADDRESS = '192.168.50.10'
API_ADDRESS = "http://%s:%s" % (BROKER_ADDRESS, '5009')
TEST_DEVICE_ID = 2


def run(device_id):
    api_url = "http://192.168.50.10:5009/api/set-display"
    payload = {
        "devices": device_id,
        # "url": random_url()
        "url": "http://192.168.50.10:5000/devices/"
    }

    response = requests.post(api_url, payload)
    print("Devices:\t%s" % payload['devices'])
    print("Url:\t\t%s" % payload['url'])
    print("Response:\t%s" % response.status_code)
    print(response.json())


def random_url():
    urls = [
        'https://www.google.com',
        'https://www.reddit.com',
        'https://www.twitter.com',
        'https://twitter.com/dc_peppercon',
        'http://192.168.50.10:5000/devices/',
        'http://slashdot.org',
        'https://news.ycombinator.com/',
    ]
    return urls[random.randint(0, len(urls) - 1)]


def mqtt_pub_url():
    device_ids = [TEST_DEVICE_ID]
    for device_id in device_ids:
        payload = {
            'device_id': device_id,
            'command': 'set_url',
            'url': random_url()
        }
        client = mqtt.Client('kio')
        client.connect(BROKER_ADDRESS, keepalive=60)
        client.publish(MQTT_TOPIC, payload=json.dumps(payload), retain=False)
        print('Published message')
        print("\t Topic: %s \n\t%s" % (MQTT_TOPIC, payload))


def mqtt_pub_reboot():
    device_ids = [TEST_DEVICE_ID]
    for device_id in device_ids:
        payload = {
            'device_id': device_id,
            'command': 'reboot',
        }
        client = mqtt.Client('kio')
        client.connect(BROKER_ADDRESS, keepalive=60)
        client.publish(MQTT_TOPIC, payload=json.dumps(payload), retain=False)
        print('Published message')
        print("\t Topic: %s \n\t%s" % (MQTT_TOPIC, payload))


def mqtt_pub_toggle(value=0):
    device_ids = [TEST_DEVICE_ID]
    for device_id in device_ids:
        payload = {
            'device_id': device_id,
            'command': 'display_toggle',
            'value': value
        }
        client = mqtt.Client('kio')
        client.connect(BROKER_ADDRESS, keepalive=60)
        client.publish(MQTT_TOPIC, payload=json.dumps(payload), retain=False)
        print('Published message')
        print("\t Topic: %s \n\t%s" % (MQTT_TOPIC, payload))


def api_reboot():
    url = "%s/command/device-reboot" % API_ADDRESS
    payload = {
        'device_id': TEST_DEVICE_ID,
    }
    response = requests.post(url, payload)
    print(response)
    print(response.json())

if __name__ == "__main__":
    # api_reboot()
    # mqtt_sub()
    # mqtt_pub_url()
    # mqtt_pub_reboot()
    mqtt_pub_toggle(1)
    # run(sys.argv[1])
