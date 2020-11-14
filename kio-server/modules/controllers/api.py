"""API Controller

"""
import json

import arrow

from flask import Blueprint, request, jsonify
from flask import current_app as app

from .. import db
from .. import mqtt_handler
from ..models.device import Device as DeviceModel
from ..models.device_cmd import DeviceCmd as DeviceCmdModel


api = Blueprint('Api', __name__, url_prefix='/api')


@api.route('cmd', methods=["POST"])
def cmd() -> str:
    """Route send generic commands to Kios. """
    data = {}
    payload = _parse_request(request.data)
    devices = _parse_devices(payload)
    device_cmd_ids = _create_device_cmds(devices, payload)
    _send_cmd_to_mqtt(device_cmd_ids)
    data['status'] = 'succeeded'
    return jsonify({})


def _parse_request(data):
    """The data coming to the API and return json data. """
    ret_data = data.decode()
    return json.loads(ret_data)


def _parse_devices(payload):
    if 'device_id' in payload:
        return [payload['device_id']]


def _create_device_cmds(devices, payload) -> list:
    """Create the DeviceCmd records, defining a new command that has been received from the API. """
    conn, cursor = db.connect(app.config['KIO_SERVER_DB'])
    device_cmd_ids = []
    for device_id in devices:
        now = arrow.utcnow()
        # Create the device_cmd and get it's id
        device_cmd = DeviceCmdModel(conn, cursor)
        device_cmd.device_id = device_id
        device_cmd.type = payload['cmd']
        if 'value' in payload:
            device_cmd.command = payload['value']
        device_cmd.api_received_ts = now
        device_cmd.status = 'issued'
        device_cmd.save()

        # Update the device with its last cmd details
        device = DeviceModel(conn, cursor)
        device.get_by_id(device_id)
        device.updated_ts = now
        device.last_command_id = device_cmd.id
        device.last_command_ts = now
        device.save()

        device_cmd_ids.append(device_cmd.id)

    return device_cmd_ids


def _send_cmd_to_mqtt(device_cmd_ids: list) -> dict:
    """Send the cmd type and cmd id to MQTT """
    for device_cmd_id in device_cmd_ids:
        mq_payload = {
            'cmd_type': 'device',
            'device_cmd_id': device_cmd_id
        }
        print('MQ PAYLOAD')
        print(mq_payload)
        mqtt_handler.publish(mq_payload)

    return True


# End File: kio/kio-server/modules/controllers/api.py
