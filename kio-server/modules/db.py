"""Database handler.
Handles the raw database connections, and database initialization of tables and required values.

"""
import os
import logging
import sqlite3

import mysql.connector
from mysql.connector import Error as MySqlError
from flask import g

def connect(server: dict):
    """Connect to the database with the given credentials OR environmental variables, returning a
       connection and cursor object.
    """
    if os.environ.get('KIO_SERVER_DB_DRIVER') == 'mysql':
        server = {
            'host': os.environ.get('KIO_SERVER_DB_HOST'),
            'port': os.environ.get('KIO_SERVER_DB_PORT'),
            'user': os.environ.get('KIO_SERVER_DB_USER'),
            'pass': os.environ.get('KIO_SERVER_DB_PASS'),
            'name': os.environ.get('KIO_SERVER_DB_NAME'),
        }
        return connect_mysql(server)
    else:
        logging.error('Invalid database driver: "%s"' % os.environ.get('KIO_SERVER_DB_DRIVER'))
        return False


def connect_mysql(server: dict):
    """Connect to MySql server and get a cursor object."""
    try:
        connection = mysql.connector.connect(
            host=server['host'],
            user=server['user'],
            password=server['pass'],
            database=server['name'])
        if connection.is_connected():
            db_info = connection.get_server_info()
            logging.debug(db_info)
            cursor = connection.cursor()
            cursor.execute("select database();")
            record = cursor.fetchone()
            logging.debug(record)
            logging.info('Connected to database: %s' % server['host'])
        return connection, cursor
    except MySqlError as e:
        logging.error("Error while connecting to MySQL", e)
        exit(1)


# End File: kio/kio-server/modules/db.py
