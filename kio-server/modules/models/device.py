"""Device Model

"""
from datetime import timedelta

import arrow

from .base import Base


class Device(Base):
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
                'name': 'last_command',
                'type': 'datetime'
            },
            {
                'name': 'last_command_status',
                'type': 'str'
            },
        ]
        self.setup()

    def __repr__(self):
        """Device representation show the name if we have one."""
        return "<Device: %s>" % self.name


# End File: kio/kio-server/modules/models/device.py
