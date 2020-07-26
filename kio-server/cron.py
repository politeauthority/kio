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
from modules.collections.urls import Urls as UrlsCollect

from modules.models.entity_meta import EntityMeta as EntityMetaModel
from modules.models.device import Device as DeviceModel
from modules.models.device_cmd import DeviceCmd as DeviceCmdModel
from modules.models.url import Url as UrlModel
from modules.models.playlist import Playlist as PlaylistModel

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
        # self.make_pl()
        self.run_playlists()

    def hello(self):
        dc = DevicesCollect(self.conn, self.cursor)
        devices = dc.get_all()
        if not devices:
            logging.warning('No registered kio devices found.')
            self.test_make_default_device()
            self.test_make_pl()
        for device in devices:
            self.check_device(device)

    def check_device(self, device):
        print('Checking device %s' % device.name)
        device.conn = self.conn
        device.cursor = self.cursor
        status_url = "%s/status" % device.address
        response = requests.get(status_url)
        if response.status_code in [200]:
            device.updated_ts = arrow.utcnow().datetime
            device.last_seen = arrow.utcnow().datetime
            device.save()
        print(response.json())

    def run_playlists(self):
        logging.info('Running Playlists')
        dc = DevicesCollect(self.conn, self.cursor)
        devices = dc.get_all()

        for device in devices:
            self.run_playlist_device(device)


    def run_playlist_device(self, device):
        device.connect(self.conn, self.cursor)
        device.load_meta()

        print(device.name)

        device_playlist = device.get_meta('playlist_id')
        if not device_playlist:
            return False

        print('Device has playlst')
        print(device_playlist.value)
        playlist = PlaylistModel(self.conn, self.cursor)
        playlist.get_by_id(device_playlist.value)

        if not playlist:
            logging.warning('No Playlist found for ID: %s ' % device.metas['playlist_id'].value)
            return False


        url_ids = playlist.urls.split(',')
        url_collect = UrlsCollect(self.conn, self.cursor)
        playlist_urls = url_collect.get_by_ids(url_ids)


        # If the last command was a playlist command, find where we are in the playlist, and play
        # the next url.
        last_command = device.last_command()
        now = arrow.utcnow()

        if last_command: 
            if last_command.created_ts > now.shift(seconds=-20).datetime:
                print(last_command.created_ts)
                print(now.shift(minutes=-1).datetime)
                print('not very old skipping ')
                return
        playlist_key = 0
        if last_command.type == "playlist":
            c = 0
            for playlist_url in playlist_urls:
                if last_command.command == playlist_url.address:
                    playlist_key = c +1
                    break
                c += 1

        if playlist_key >= len(playlist_urls):
            playlist_key = 0

        device.cmd(playlist_urls[playlist_key].address, 'playlist')


    def test_make_pl(self):
        url_ids = []
        url1 = UrlModel(self.conn, self.cursor)
        url1.name = "Lan Nanny"
        url1.address = "http://192.168.50.10:5000/devices/online"
        url1.save()
        url_ids.append(url1.id)
        print(url1.id)


        url2 = UrlModel(self.conn, self.cursor)
        url2.name = "Octo Print"
        url2.address = "http://192.168.50.235/#gcode"
        url2.save()
        url_ids.append(url2.id)
        print(url2.id)


        url3 = UrlModel(self.conn, self.cursor)
        url3.name = "DakBoard"
        url3.address = "https://dakboard.com/app/screenPredefined?p=7db341a0097ced9f618266c704afc279"
        url3.save()
        url_ids.append(url3.id)
        print(url3.id)


        pl = PlaylistModel(self.conn, self.cursor)
        pl.name = "First"
        print(url_ids)
        url_ids_str = ""
        for u in url_ids:
            url_ids_str += "%s," % str(u)
        url_ids_str = url_ids_str[:-1]
        pl.urls = url_ids_str
        print(pl.urls)
        pl.save()

        device = DeviceModel(self.conn, self.cursor)
        device.get_by_id(1)
        device.metas['playlist_id'] = EntityMetaModel(self.conn, self.cursor)
        device.metas['playlist_id'].create(
                meta_name='playlist_id',
                meta_type='int',
                meta_value=1)
        device.save()

    def test_make_default_device(self):
        device = DeviceModel(self.conn, self.cursor)
        device.name = "Main"
        device.address = "http://192.168.50.117:8001"
        device.save()
        logging.info('Created device %s' % device.address)

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
