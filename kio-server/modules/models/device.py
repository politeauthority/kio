"""Device Model

"""
import requests

from .base_entity_meta import BaseEntityMeta
from .device_cmd import DeviceCmd


class Device(BaseEntityMeta):
    """Device object, representing a Kio registered device."""

    def __init__(self, conn=None, cursor=None):
        """Device init for a new device object, passing SQLite connection parameters."""
        super(Device, self).__init__(conn, cursor)
        self.table_name = 'devices'

        self.field_map = [
            {
                'name': 'name',
                'type': 'str'
            },
            {
                'name': 'address',
                'type': 'str'
            },
            {
                'name': 'last_seen',
                'type': 'datetime'
            },
            {
                'name': 'last_command_id',
                'type': 'int'
            },
            {
                'name': 'last_command_ts',
                'type': 'datetime'
            },
            {
                'name': 'last_command_status',
                'type': 'str'
            },
            {
                'name': 'online',
                'type': 'bool'
            },
        ]
        self.setup()

    def __repr__(self):
        """Device representation show the name if we have one."""
        return "<Device: %s>" % self.name

    def cmd(self, url, type):
        """ """
        dc = DeviceCmd(self.conn, self.cursor)
        dc.device_id = self.id
        dc.type = type
        dc.command = url

        device_url = "%s/set-display" % self.address

        payload = {
            'url': url
        }
        print(url)
        print(payload)
        response = requests.get(device_url, payload)
        print(response)

        if response.status_code not in ['200']:
            dc.status = "failed"
        dc.status = "succeeded"
        dc.save()
        return dc.status

    def last_command(self):
        dc = DeviceCmd(self.conn, self.cursor)
        dc.last_command(self.id)
        return dc





# End File: kio/kio-server/modules/models/device.py
