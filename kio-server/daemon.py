"""Daemon
This is the process which subscribes to messages being sent to the MQTT broker for kio, and then
sends the relevant commands on to the Kio-Nodes.

"""
import json
from importlib import import_module
import logging
import logging.config
import os
import traceback

import requests
import paho.mqtt.client as mqtt

from modules import db
from modules.models.device import Device as DeviceModel

BROKER_ADDRESS = os.environ.get('KIO_SERVER_MQTT_HOST')
MQTT_TOPIC = os.environ.get('KIO_SERVER_MQTT_TOPIC')


class Daemon:

    def __init__(self, configs):
        self.conn, self.cursor = db.connect(configs.KIO_SERVER_DB)
        self.config = configs

    def setup(self):
        """Sets up run log and loads options."""
        self.setup_logging()
        # options = Options(self.conn, self.cursor)
        # self.options = options.get_all_keyed('name')
        # self.tmp_dir = self.config.KIO_SERVER_TMP
        # if self.args.cron:
            # self.trigger = 'cron'
        # logging.info('Script triggered by %s' % self.trigger)
        logging.info('Logging Setup')

    def setup_logging(self) -> bool:
        """Create the logger."""
        log_level = logging.DEBUG
        logging.basicConfig(
            format='%(asctime)s [%(levelname)s]\t%(message)s',
            datefmt='%m/%d/%Y %I:%M:%S %p',
            level=0,
            handlers=[logging.StreamHandler()])

        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug('Logging enabled - debug')
        # Squelch urlib3/requests debug logs
        logging.getLogger("requests").setLevel(logging.WARNING)
        return True

    def run(self):
        """Start the Kio subscriber daemon to listen to messages published on the MQTT broker for
           kio.
        """
        self.setup()
        client = mqtt.Client("kio-sub")  # Create instance of client with client ID “digi_mqtt_test”
        client.on_connect = self.on_connect  # Define callback function for successful connection
        client.on_message = self.on_message  # Define callback function for receipt of a message
        # client.connect("m2m.eclipse.org", 1883, 60)  # Connect to (broker, port, keepalive-time)
        client.connect(BROKER_ADDRESS)
        client.loop_forever()  # Start networking daemon

    def on_connect(self, client, userdata, flags, rc) -> bool:
        """The callback for when the client connects to the broker. """
        if rc == 0:
            logging.info("Connected to MQTT broker successfully")
        else:
            logging.error("Failed connecting to MQTT broker %s" % BROKER_ADDRESS)
            return False
        client.subscribe(MQTT_TOPIC)
        return True

    def on_message(self, client, userdata, msg):
        """The callback for when a PUBLISH message is received from the server. """
        try:
            logging.info("Message received-> " + msg.topic + " " + str(msg.payload))  # Print a received msg
            msg_payload = json.loads(msg.payload)
            self.route_device_msg(msg_payload)
        except:
            traceback.print_exc()
            quit(0)

    def route_device_msg(self, payload):
        logging.debug('in route_device_msg')
        device = DeviceModel(self.conn, self.cursor)
        device.get_by_id(payload['device_id'])
        logging.debug(device)
        self.device_cmd(device, payload)

    def device_cmd(self, device, payload):
        logging.info('Sending device %s cmd: %s' %(device, payload['command']))
        if payload['command'] == 'display_set':
            logging.info("\tDevice url: %s" % payload['url'])
            response = device.cmd('display_set', {'url': payload['url']})

        elif payload['command'] == 'display_reboot':
            logging.info("\tDevice reboot")
            response = device.cmd('reboot')

        elif payload['command'] == 'display_toggle':
            logging.info("\tDevice display toggle")
            response = device.cmd('display_toggle', {'value': payload['value']})

        logging.info(response)




def get_config():
    """Get the application configs."""
    if os.environ.get('KIO_SERVER_CONFIG'):
        config_file = os.environ.get('KIO_SERVER_CONFIG')
        configs = import_module('config.%s' % config_file)
        print('Using config: %s' % os.environ.get('KIO_SERVER_CONFIG') )
    else:
        print('Using config: default')
        configs = import_module('config.default')
    return configs



if __name__ == "__main__":
    configs = get_config()
    Daemon(configs).run()


# End File: kio/kio-server/daemon.py
