"""Config Help

"""
from importlib import import_module
import os 

CONFIG_ENV_NAME = "KIO_SERVER_CONFIG"

def get_config():
    """Get the application configs."""
    print(CONFIG_ENV_NAME)
    print(os.environ.get(CONFIG_ENV_NAME))
    if os.environ.get(CONFIG_ENV_NAME):
        print(CONFIG_ENV_NAME)
        config_file = os.environ.get(CONFIG_ENV_NAME)
        configs = import_module('config.%s' % config_file)
        # imported_module = import_module('.config.%s' % config)
        print('Using config: %s' % os.environ.get(CONFIG_ENV_NAME) )
    else:
        print('Using config: default')
        configs = import_module('config.default')
    return configs

# End File: kio/kio-server//modules/configer.py
