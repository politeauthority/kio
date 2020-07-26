"""Database handler.
Handles the raw database connections, and database initialization of tables and required values.

"""
import logging
import sqlite3

from flask import g


def get_db_flask(database_file: str):
    """Create a database connection to a SQLite database for the flask web environment."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(database_file)
    return db, db.cursor()


def get_db(database_file):
    conn = None
    conn = sqlite3.connect(database_file)
    return conn, conn.cursor()


# End File: kio/kio-server/modules/db.py
