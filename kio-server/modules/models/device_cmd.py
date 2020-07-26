"""Device Cmd Model

"""
from .base import Base


class DeviceCmd(Base):
    """DeviceCmd object. """

    def __init__(self, conn=None, cursor=None):
        super(DeviceCmd, self).__init__(conn, cursor)
        self.table_name = 'device_cmds'

        self.field_map = [
            {
                'name': 'device_id',
                'type': 'int'
            },
            {
                'name': 'type',
                'type': 'str'
            },
            {
                'name': 'command',
                'type': 'str'
            },
            {
                'name': 'status',
                'type': 'str'
            },
        ]
        self.setup()

    def __repr__(self):
        """Device representation show the command if we have one."""
        return "<DeviceCmd: %s>" % self.command


# End File: kio/kio-server/modules/models/device_cmd.py
