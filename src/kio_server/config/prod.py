"""Prod configs

"""
import os

DEBUG = False
KIO_SERVER_DATA = "/opt/kio"
KIO_SERVER_TMP = "/tmp"
KIO_SERVER_CRON_LOG = os.path.join(KIO_SERVER_DATA, "cron.log")
KIO_SERVER_DB = os.path.join(KIO_SERVER_DATA, "kio.db")

# End File: kio/kio-server/config/prod.py
