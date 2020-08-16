"""Install / Upgrade script for Kio
This process can be run safely at anytime to setup a new or in place upgrade and existing install.

"""
import logging
import os
import subprocess

from modules import configer
from modules import db
from modules.models.entity_meta import EntityMeta
from modules.models.option import Option
from modules.models.device import Device
from modules.models.device_cmd import DeviceCmd
from modules.models.url import Url
from modules.models.playlist import Playlist

class InstallUpgrade:

    def run(self):
        """Run the install/upgrader. """
        self.setup_logging()
        # Get the config
        self.config = configer.get_config()

        print(self.config.KIO_SERVER_DB)
        # Setup Kio dir
        self.setup_kio_dir()

        # Get the Database
        self.conn, self.cursor = self.get_database(self.config.KIO_SERVER_DB)

        # Create the Database and tables
        self.create_tables()


    def setup_logging(self) -> bool:
        """Create the logger."""
        log_level = logging.INFO
        logging.basicConfig(
            format='%(asctime)s [%(levelname)s]\t%(message)s',
            datefmt='%m/%d/%Y %I:%M:%S %p',
            level=log_level,
            handlers=[logging.StreamHandler()])

    def setup_kio_dir(self):
        kio_path = self.config.KIO_SERVER_DATA
        if not os.path.exists(kio_path):
            os.makedirs(self.config.KIO_SERVER_DATA)
        
        print("chmod -R 777 %s" % self.config.KIO_SERVER_DATA)
        subprocess.call("chmod -R 777 %s" % self.config.KIO_SERVER_DATA, shell=True)

    def change_permissions_recursive(self, path, mode):
        for root, dirs, files in os.walk(path, topdown=False):
            for dir in [os.path.join(root,d) for d in dirs]:
                os.chmod(dir, mode)
        for file in [os.path.join(root, f) for f in files]:
                os.chmod(file, mode)

    def get_database(self, server_file):
        """Create the Lan Nanny database if it's not existent, then return the MySql connection."""
        conn, cursor = db.connect(server_file)
        logging.info('Database connection successful')
        return conn, cursor

    def create_tables(self):
        """Create the tables if they don't exist. """
        logging.info('Creating tables')
        # Create base tables
        self._create_model_table('Entity_Meta')
        self._create_model_table('Option')
        # Create app tables
        self._create_model_table('Device')
        self._create_model_table('Device_Cmd')
        self._create_model_table('Url')
        self._create_model_table('Playlist')


    def _create_model_table(self, model: str):
        """Create the tables for the requested model. This requires the model to still be manually
           imported.
        """
        model_file = model.lower()
        model_class = model.replace("_", "")
        model = self._import_model('modules.models.%s.%s' % (model_file, model_class ))
        obj = model(self.conn, self.cursor)
        obj.create_table()
        logging.info('Created:\t%s' % obj.table_name)

    def _import_model(self, name: str):
        """Dynamically selects an imported model based on it's path. """
        components = name.split('.')
        mod = __import__(components[0])
        for comp in components[1:]:
            mod = getattr(mod, comp)
        return mod


if __name__ == "__main__":
    InstallUpgrade().run()


# End File: kio/kio-server/install-upgrade.py
