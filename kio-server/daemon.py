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

import arrow
import requests
import paho.mqtt.client as mqtt

from modules import db
from modules.models.device import Device as DeviceModel
from modules.models.device_cmd import DeviceCmd as DeviceCmdModel

BROKER_ADDRESS = os.environ.get('KIO_SERVER_MQTT_HOST')
BROKER_PORT = 1883
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

        logging.getLogger().setLevel(logging.INFO)
        logging.debug('Logging enabled - debug')
        # Squelch urlib3/requests debug logs
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        return True

    def run(self):
        """Start the Kio subscriber daemon to listen to messages published on the MQTT broker for
           kio.
        """
        self.setup()
        client = mqtt.Client()  # Create instance of client with client ID “digi_mqtt_test”
        client.connect(BROKER_ADDRESS, BROKER_PORT)

        client.on_connect = self.on_connect  # Define callback function for successful connection
        client.on_message = self.on_message  # Define callback function for receipt of a message
        client.subscribe(MQTT_TOPIC, 1)
        loop = client.loop_forever()  # Start networking daemon

    def on_connect(self, client, userdata, flags, rc) -> bool:
        """The callback for when the client connects to the broker. """
        if rc == 0:
            logging.info(
                "Connected to MQTT broker %s subscribing to topic: %s" % (BROKER_ADDRESS, MQTT_TOPIC))
        else:
            logging.error("Failed connecting to MQTT broker %s" % BROKER_ADDRESS)
            return False
        
        return True

    def on_message(self, client, userdata, msg) -> bool:
        """The callback for when a PUBLISH message is received from the server. """
        print('GOT MESSAGE')
        try:
            logging.info("Message received -> " + msg.topic + " " + str(msg.payload))  # Print a received msg
            msg_payload = json.loads(msg.payload)

            valid_cmd_types = ["device"]
            if 'cmd_type' not in msg_payload:
                print('Error: MQTT payload does not contain a "cmd_type".')
                return False
            # If the command type is not a valid command return False
            if msg_payload['cmd_type'] not in valid_cmd_types:
                print('Error: Unknown MQTT payload cmd_type "%s"' % msg_payload['cmd_type'])
                return False

            self.handle_device_cmd(msg_payload)
            return True

        except:
            traceback.print_exc()
            quit(0)

    def handle_device_cmd(self, payload):
        """ """
        device_cmd = DeviceCmdModel(self.conn, self.cursor)
        device_cmd.get_by_id(payload['device_cmd_id'])

        device_cmd.status = "received"
        device_cmd.mqtt_recieved_ts = arrow.utcnow()
        device_cmd.save()

        device = DeviceModel(self.conn, self.cursor)
        device.get_by_id(device_cmd.device_id)
        return self.issue_cmd_to_device(device, device_cmd)

    def issue_cmd_to_device(self, device, device_cmd) -> bool:
        """Fire the command off the Kio-Node's API"""
        if device_cmd.type == 'display_set':
            device_url = "%s/display-set" % device.address
            payload = {'url': device_cmd.command}
            log_text = "%s - %s" % (device_cmd.type, device_cmd.command)

        elif device_cmd.type == 'display_toggle':
            device_url = "%s/display-toggle" % device.address
            payload = {'value': device_cmd.command}
            log_text = "%s - %s" % (device_cmd.type, device_cmd.command)

        elif device_cmd.type == 'display_reboot':
            device_url = "%s/reboot" % device.address
            payload = {}
            log_text = "%s" % (device_cmd.type)

        else:
            logging.error('Unknown device cmd: "%s"' % device_cmd.type)
            device_cmd.status = "failed - bad device cmd"
            device_cmd.save()
            return False

        logging.info('Sending command to Kio-Node: %s - %s' % (device, log_text))
        now = arrow.utcnow()
        node_response = requests.get(device_url, payload)

        # Handle node response errors
        if node_response.status_code not in [200]:
            logging.error('Node Responded with status code: %s' % node_response.status_code)
            device_cmd.status = 'failed - node response %s' % node_response.status_code
            device_cmd.save()
            device.last_seen = now
            device.updated_ts = now
            device.save()
            return False

        node_response_json = node_response.json()

        if node_response_json['status'] == 'success':
            device_cmd.status = 'complete'
            device_cmd.completed_ts = arrow.utcnow()
        device_cmd.save()

        # Update the device record with info from the response
        device.last_seen = now
        device.updated_ts = now
        if 'kio-node' in node_response_json:
            device.server_version = node_response_json['kio-node']
        device.save()


        if device_cmd.status == 'complete':
            logging.info('Request status: success')
            return True
        else:
            logging.warning('Request status: failed')
            return False


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
