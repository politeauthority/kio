"""Device Controller

"""
from flask import Blueprint, render_template, request, redirect
from flask import current_app as app

from .. import db
from ..models.device import Device as DeviceModel
from ..collections.devices import Devices as DevicesCollect


devices = Blueprint('Devices', __name__, url_prefix='/devices')



@devices.route('/')
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
    return render_template('devices/dashboard.html', **data)


@devices.route('info/<device_id>')
def info(device_id: int) -> str:
    """Device info page."""
    conn, cursor = db.get_db_flask(app.config['KIO_SERVER_DB'])
    device = DeviceModel(conn, cursor)
    device.get_by_id(device_id)
    print(device)
    print(device.name)
    print(device.address)
    data = {
        "device": device
    }
    return render_template('devices/info.html', **data)


@devices.route('/create')
def create() -> str:
    """Create Device form."""
    data = {}
    data['form'] = 'new'
    data['device'] = None
    return render_template('devices/create.html', **data)


@devices.route('/save', methods=['POST'])
def save():
    """Device save, route for new and editing devices."""
    conn, cursor = db.get_db_flask(app.config['KIO_SERVER_DB'])
    device = DeviceModel(conn, cursor)
    if request.form['device_id'] != 'new':
        device.get_by_id(request.form['device_id'])
        if not device.id:
            return 'ERROR 404: Route this to page_not_found method!', 404
            # return page_not_found('Device not found')

    device.name = request.form['device_name']
    device.address = request.form['device_address']
    device.save()

    return redirect('/devices/info/%s' % device.id)

# End File: kio/kio-server/modules/controllers/device.py
