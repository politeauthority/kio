"""Docker configs

"""
import os

DEBUG = False
KIO_SERVER_DATA = "/opt/kio-dev"
KIO_SERVER_TMP = "/tmp"
KIO_SERVER_CRON_LOG = os.path.join(KIO_SERVER_DATA, "cron.log")

# End File: kio/kio-server/config/docker.py
