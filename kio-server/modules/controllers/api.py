"""API Controller

"""
from flask import Blueprint, request, jsonify
from flask import current_app as app

from .. import db
from .. import mqtt_handler
from ..models.device import Device as DeviceModel
from ..collections.devices import Devices as DevicesCollect

import json


api = Blueprint('Api', __name__, url_prefix='/api')


@api.route('cmd', methods=["POST"])
def cmd() -> str:
    """Route send generic commands to Kios. """
    display_cmd = "display_toggle"
    data = {}
    data['cmd'] = display_cmd
    print("\n\n")
    print("API CMD")
    print(request.data)
    payload = _parse_request(request.data)
    print(payload)
    print("\n\n")

    devices = _parse_devices(payload)

    _send_request(devices, payload)

    # payload = _parse_request(request.data)

    # cmd = request.data.get('cmd')
    # for key, value in request.data.items():
    #     print("Key: %s\tValue: %s" % (key, value))
    # devices = _get_request_devices()
    # payload = {
    #     'value': request.args.get('value')
    # }
    # data['devices'] = _send_requests(devices, display_cmd, payload)
    # data['status'] = 'succeeded'
    return jsonify(data)


@api.route('display-set')
def display_set() -> str:
    """Route to set the selected Kio-Nodes to load a given URL. """
    display_cmd = "display_set"
    data = {}
    data['cmd'] = display_cmd
    devices = _get_request_devices()
    payload = {
        'url': request.args.get('url')
    }
    data['devices'] = _send_requests(devices, display_cmd, payload)
    data['status'] = 'succeeded'
    return jsonify(data)


@api.route('display-toggle', methods=["GET", "POST"])
def display_toggle() -> str:
    """Route to toggle the Kio-Nodes display on/off. """
    display_cmd = "display_toggle"
    data = {}
    data['cmd'] = display_cmd
    devices = _get_request_devices()
    payload = {
        'value': request.args.get('value')
    }
    data['devices'] = _send_requests(devices, display_cmd, payload)
    data['status'] = 'succeeded'
    return jsonify(data)


@api.route('display-reboot')
def display_reboot() -> str:
    """Route to reboot the Kio-Nodes selected. """
    display_cmd = "display_reboot"
    data = {}
    data['cmd'] = display_cmd
    devices = _get_request_devices()
    data['devices'] = _send_requests(devices, display_cmd)
    data['status'] = 'succeeded'
    return jsonify(data)


def _get_request_devices() -> list:
    """Get the devices mentioned in the request, and return hydrated objects in a list. """
    request_devices = request.args.get('device_id')

    if not request_devices:
        request_devices = request.args.get('device_ids')
    
    print("\n\n")
    print(request.data)
    print(request_devices)
    print("\n\n")
    if ',' in request_devices:
        request_devices = request_devices.split(',')

    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    cdevices = DevicesCollect(conn, cursor)
    
    # Determine the devices to command
    if request_devices == 'all':
        the_devices = cdevices.get_all()
    else:
        the_devices = cdevices.get_by_ids(request_devices)

    return the_devices


def _send_requests(devices, cmd, payload: dict={}) -> dict:
    """Fire off requests to the given Devices. """
    request_data = {}
    for device in devices:
        response = device.cmd(cmd, payload)
        queue_payload = {
            'device_id': device.id,
        }
        queue_payload.update(payload)
        mqtt_handler.publish(queue_payload)
        request_data[device.id] = {
            'device_id': device.id,
            'device_name': device.name,
            'response': response,
        }
    return request_data

def _send_request(devices: list, payload: dict={}) -> dict:
    """Fire off requests to the given Devices by submitting the data to MQTT. """
    request_data = {}
    for device in devices:
        # response = device.cmd(cmd, payload)
        mqtt_handler.publish(payload)
        # request_data[device.id] = {
        #     'device_id': device.id,
        #     'device_name': device.name,
        #     'response': response,
        # }
    return request_data


def _parse_request(data):
    """The data coming from the """
    ret_data = data.decode()
    return json.loads(ret_data)

def _parse_devices(payload):
    if 'device_id' in payload:
        return [payload['device_id']]

# End File: kio/kio-server/modules/controllers/api.py
