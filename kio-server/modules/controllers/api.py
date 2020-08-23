"""Api Controller

"""
from flask import Blueprint, jsonify, request
from flask import current_app as app

from .. import db
from ..collections.devices import Devices as CollectDevices

api = Blueprint('Api', __name__, url_prefix='/api')


@api.route('/set-display', methods=["POST"])
def set_url() -> str:
    """Set devices immediately to the requested url. """
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    devices = _get_devices(conn, cursor, request.form['devices'])
    url = request.form['url']
    data = {
        'devices': []
    }
    for device in devices:
        status = device.cmd(url)
        device_cmd = {
            'device_id': device.id,
            'status': status,
            'url': url,
        }
        data['devices'].append(device_cmd)
    return jsonify(data)


def _get_devices(conn, cursor, devices: str) -> list:
    """Get a list of Device objects from an incoming API request. """
    raw_device_ids = _parse_devices(request.form['devices'])
    device_collect = CollectDevices(conn, cursor)
    devices = device_collect.get_by_ids(raw_device_ids)
    return devices


def _parse_devices(devices: str) -> list:
    """Parses a comma separated set of devices into a list of ints. """
    clean_devices = []
    if ',' in devices:
        clean_devices = devices.split(',')
    else:
        clean_devices = [devices]

    ret_devices = []
    for device in clean_devices:
        ret_devices.append(int(device))

    return ret_devices


# End File: kio/kio-server/modules/controllers/api.py
