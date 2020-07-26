"""Install / Upgrade script for Kio
This process can be run safely at anytime to setup a new or in place upgrade and existing install.

"""
import logging

from modules import configer
from modules import db
from modules.models.entity_meta import EnityMeta
from modules.models.device import Device
from modules.models.url import Url

class InstallUpgrade:

    def run(self):
        """Run the install/upgrader. """
        self.setup_logging()
        # Get the config
        config = configer.get_config()
        # Get the Database
        self.conn, self.cursor = self.get_database(config.KIO_SERVER_DB)

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

    def get_database(self, server_file):
        """Create the Lan Nanny database if it's not existent, then return the MySql connection."""
        conn, cursor = db.get_db(server_file)
        logging.info('Database connection successful')
        return conn, cursor

    def create_tables(self):
        logging.info('Creating tables')
        self._create_model_table('Device')


    def _create_model_table(self, model):
        model = self._import_model('modules.models.%s.%s' % (model.lower(), model))
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
