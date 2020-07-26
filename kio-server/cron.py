"""Entry point to all scan operations and other tasks that need to be run on a regular schedule.

    Scans hosts on network
    Scans ports for a given host
    Runs house keeping operations.

    This script must be run with sudo privileges for network scanning to work properly.

"""
import argparse
from importlib import import_module
import logging
import logging.config
import os

import arrow
import requests

from modules import db
from modules.collections.options import Options
from modules.collections.devices import Devices as DevicesCollect

class Cron:

    def __init__(self, configs, args):
        """
        :param configs: LanNanny application configs.
        :param args: CLI arguments
        """
        self.conn, self.cursor = db.get_db(configs.KIO_SERVER_DB)
        self.args = args
        self.trigger = 'manual'
        self.config = configs

    def setup(self):
        """Sets up run log and loads options."""
        self.setup_logging()
        options = Options(self.conn, self.cursor)
        self.options = options.get_all_keyed('name')
        self.tmp_dir = self.config.KIO_SERVER_TMP
        if self.args.cron:
            self.trigger = 'cron'
        logging.info('Script triggered by %s' % self.trigger)

    def setup_logging(self) -> bool:
        """Create the logger."""
        log_level = logging.INFO
        if self.args.verbose:
            log_level = logging.DEBUG
        logging.basicConfig(
            format='%(asctime)s [%(levelname)s]\t%(message)s',
            datefmt='%m/%d/%Y %I:%M:%S %p',
            level=log_level,
            handlers=[logging.FileHandler(self.config.KIO_SERVER_CRON_LOG),
                  logging.StreamHandler()])

        return True

    def run(self):
        """Main entry point to scanning script."""
        self.setup()
        self.hello()

    def hello(self):
        dc = DevicesCollect(self.conn, self.cursor)
        devices = dc.get_all()
        for device in devices:
            self.check_device(device)

    def check_device(self, device):
        print('Checking device %s' % device.name)
        device.conn = self.conn
        device.cursor = self.cursor
        status_url = "http://%s/status" % device.address
        response = requests.get(status_url)
        if response.status_code in [200]:
            device.last_seen = arrow.utcnow().datetime
            device.save()
        print(response.json())


def parse_args():
    """
    Parses args from the cli with ArgumentParser
    :returns: Parsed arguments
    :rtype: <Namespace> obj
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cron",
        default=False,
        action='store_true',
        help="")
    parser.add_argument(
        "--verbose",
        default=False,
        action='store_true',
        help="Run at debug logging level")
    args = parser.parse_args()
    return args

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


if __name__ == '__main__':
    args = parse_args()
    configs = get_config()
    Cron(configs, args).run()


# End File: kio/kio-server/cron.py
