"""App Entry Point.
Web application entry point.

"""
import os
import sys

from flask import Flask, jsonify, request, render_template, g

from modules import db
from modules.controllers.devices import devices as ctrl_devices
from modules.controllers.command import command as ctrl_command

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
    """ App Index."""
    data = {}
    return render_template("dashboard.html")

    
def register_blueprints(app: Flask):
    """Connect the blueprints to the router."""
    app.register_blueprint(ctrl_devices)
    app.register_blueprint(ctrl_command)


register_blueprints(app)

if __name__ == '__main__':
    port = sys.argv[1]
    app.secret_key = 'super secret key'
    app.run(host="0.0.0.0", port=port, debug=True)

# End File: kio/kio-server/kio-server.py
