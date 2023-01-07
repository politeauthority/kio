"""Device Controller

"""
from flask import Blueprint, render_template, request, redirect, jsonify
from flask import current_app as app

import requests

from kio_server.utils import db
from kio_server import mqtt_handler
from kio_server.models.device import Device as DeviceModel
from kio_server.collections.devices import Devices as DevicesCollect


command = Blueprint('Command', __name__, url_prefix='/command')


@command.route('/')
def index() -> str:
    """Device roster page."""
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
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
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    cdevices = DevicesCollect(conn, cursor)
    
    # Determine the devices to command
    cmd_devices = request.form['cmd_now_device']
    if cmd_devices == 'all':
        the_devices = cdevices.get_all()
    else:
        the_devices = cdevices.get_by_ids([cmd_devices])


    # Send the commands to the selected devices
    cmd_url = request.form['cmd_now_url']
    for device in the_devices:
        payload = {
            'device_id': device.id,
            'url': cmd_url,
            'command': 'display_set',
            'command_type': 'manual'
        }
        mqtt_handler.publish(payload)

    return redirect('/command/')


@command.route('/device-reboot', methods=["POST"])
def device_reboot() -> str:
    device_id = request.form['device_id']
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    device = DeviceModel(conn, cursor)
    device.get_by_id(device_id)

    payload = {
        'device_id': device.id,
        'command': 'reboot',
        'command_type': 'manual'
    }
    pub = mqtt_handler.publish(payload)
    if pub:
        status = "success"
    else:
        status = "failed"

    data = {
        'status': status
    }

    return jsonify(data)


# End File: kio/kio-server/modules/controllers/command.py
