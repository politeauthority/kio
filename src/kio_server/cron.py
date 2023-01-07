"""Cron
"""
import json
from importlib import import_module
import logging
import logging.config
import os
import random

import requests

from modules import db
from modules.models.device import Device as DeviceModel

BROKER_ADDRESS = os.environ.get('KIO_SERVER_MQTT_HOST')
MQTT_TOPIC = os.environ.get('KIO_SERVER_MQTT_TOPIC')
KIO_SERVER_URL = os.environ.get('KIO_SERVER_URL')


class Cron:

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
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        return True

    def run(self):
        """Start the Kio subscriber daemon to listen to messages published on the MQTT broker for
           kio.
        """
        self.setup()
        self.demo()
   
    def demo(self):
        url = "%s/api/cmd" % KIO_SERVER_URL
        url_list = [
            "http://192.168.50.6:3000/d/PKvXJhpMz/green-machine?orgId=2&refresh=1m",
            "https://www.google.com/search?q=westminster+weather",
            "https://dakboard.com/app?p=7db341a0097ced9f618266c704afc279",
            "http://192.168.50.190:8081",
        ]
        url_rand = random.randint(0, len(url_list) - 1)
        data = {
            'device_id': 1,
            'cmd': 'display_set',
            'value': url_list[url_rand]
        }
        logging.info("Telling %s to load %s" % (data['device_id'], data['value']))
        response = requests.post(url, json.dumps(data))
        if response.status_code == 500:
            logging.error(response.text)
        logging.info(response.json())


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
    Cron(configs).run()


# End File: kio/kio-server/daemon.py
