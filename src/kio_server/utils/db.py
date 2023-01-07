"""Utils - DB
Database handler.

"""
import os

import pymysql.cursors
import mysql.connector
from mysql.connector import Error as MySqlError

from kio_server.utils import log


DB_HOST = os.environ.get("KIO_SERVER_DB_HOST")
DB_PORT = int(os.environ.get("KIO_SERVER_DB_PORT"))
DB_NAME = os.environ.get("KIO_SERVER_DB_NAME")
DB_USER = os.environ.get("KIO_SERVER_DB_USER")
DB_PASS = os.environ.get("KIO_SERVER_DB_PASS")


def connect():
    # Connect to the database
    connection = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME)

    log.info("Generating database connection")
    return {
        "conn": connection,
        "cursor": connection.cursor()
    }


def connect_no_db(server: dict):
    """Connect to MySql server, without specifying a database, and get a cursor object."""
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS)
        if connection.is_connected():
            db_info = connection.get_server_info()
            log.debug(db_info)
            cursor = connection.cursor()
            cursor.execute("select database();")
            record = cursor.fetchone()
            log.debug(record)
        return {
            "conn": connection,
            "cursor": cursor,
        }
    except MySqlError as e:
        log.error("Error while connecting to MySQL: %s" % e, exception=e)
        exit(1)


def create_mysql_database(conn, cursor):
    """Create the MySQL database."""
    sql = """CREATE DATABASE IF NOT EXISTS %s; """ % DB_NAME
    log.info(sql)
    cursor.execute(sql)
    log.info('Created database: %s' % DB_NAME)
    return True


# End File: kio/kio-server/modules/utils/db.py
