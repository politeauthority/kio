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

    def cmd(self, cmd_type: str, recieved_payload: dict=None):
        """ """
        dc = DeviceCmd(self.conn, self.cursor)
        dc.device_id = self.id
        dc.type = cmd_type
        payload = {}

        if dc.type == 'set_url':
            set_url = recieved_payload['url']
            device_url = "%s/display-set" % self.address
            dc.command = "%s?url=%s" % (device_url, set_url)
            payload = {'url': set_url}
        elif dc.type == 'reboot':
            device_url = "%s/reboot" % self.address
            dc.command = device_url
        elif dc.type == 'display_toggle':
            value = recieved_payload['value']
            device_url = "%s/toggle-display" % self.address
            dc.command = device_url

        response = requests.get(device_url, payload)

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
