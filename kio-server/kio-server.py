"""App Entry Point.
Web application entry point.

"""
import os
import sys

from flask import Flask, jsonify, request, render_template, g

from modules import db
from modules.controllers.api import api as ctrl_api
from modules.controllers.devices import devices as ctrl_devices
from modules.controllers.command import command as ctrl_command
from modules.controllers.urls import urls as ctrl_urls
from modules.controllers.playlists import playlists as ctrl_playlists
from modules.controllers.settings import settings as ctrl_settings


app = Flask(__name__)

if os.environ.get('KIO_SERVER_CONFIG'):
    app.config.from_object('config.%s' % os.environ.get('KIO_SERVER_CONFIG'))
    print('Using config: %s' % os.environ.get('KIO_SERVER_CONFIG'))
else:
    app.config.from_object('config.default')
    print('Using config: default')


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route('/')
def index() -> str:
    """App Index. """
    data = {}
    return render_template("dashboard.html")

    
def register_blueprints(app: Flask):
    """Connect the blueprints to the router."""
    app.register_blueprint(ctrl_api)
    app.register_blueprint(ctrl_devices)
    app.register_blueprint(ctrl_command)
    app.register_blueprint(ctrl_urls)
    app.register_blueprint(ctrl_playlists)
    app.register_blueprint(ctrl_settings)


register_blueprints(app)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = 5009
    app.secret_key = 'super secret key'
    app.run(host="0.0.0.0", port=port, debug=True)

# End File: kio/kio-server/kio-server.py
