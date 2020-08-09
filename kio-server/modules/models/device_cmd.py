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


    def last_command(self, device_id):
        qry = """
            SELECT *
            FROM `%s`
            WHERE
                `device_id`=%s
            ORDER BY `created_ts` DESC
            LIMIT 1;
            """ % (self.table_name, device_id)
        self.cursor.execute(qry)
        raw = self.cursor.fetchone()
        if not raw:
            return False
        self.build_from_list(raw)
        return True


# End File: kio/kio-server/modules/models/device_cmd.py
