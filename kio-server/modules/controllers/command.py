"""Device Controller

"""
from flask import Blueprint, render_template, request, redirect
from flask import current_app as app

import requests

from .. import db
from ..models.device import Device as DeviceModel
from ..collections.devices import Devices as DevicesCollect


command = Blueprint('Command', __name__, url_prefix='/command')



@command.route('/')
def index() -> str:
    """Device roster page."""
    conn, cursor = db.get_db_flask(app.config['KIO_SERVER_DB'])
    cdevices = DevicesCollect(conn, cursor)
    all_devices = cdevices.get_all()
    data = {
        "devices": all_devices,
        "devices_total": len(all_devices),
        "active_page": "devices"

    }
    return render_template('command/dashboard.html', **data)


@command.route('/run', methods=["POST"])
def run() -> str:
    """Set devices immediately to the requested url. """
    conn, cursor = db.get_db_flask(app.config['KIO_SERVER_DB'])
    cdevices = DevicesCollect(conn, cursor)
    
    cmd_devices = request.form['cmd_now_device']
    cmd_url = request.form['cmd_now_url']
    if cmd_devices == 'all':
        the_devices = cdevices.get_all()

    for device in the_devices:
        url = "http://%s/set-display" % device.address
        payload = {
            'url': cmd_url
        }
        print(url)
        print(payload)
        response = requests.get(url, payload)
        print(response)

    return redirect('/command/')


# End File: kio/kio-server/modules/controllers/command.py
