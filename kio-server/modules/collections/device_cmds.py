"""Device Cmds Collection
Gets collections of device cmds.

"""
from .base import Base
from ..models.device_cmd import DeviceCmd


class DeviceCmds(Base):
    """Collection class for gathering groups of device device cmds."""

    def __init__(self, conn=None, cursor=None):
        """Store Sqlite conn and model table_name as well as the model obj for the collections
           target model.
        """
        super(DeviceCmds, self).__init__(conn, cursor)
        self.table_name = DeviceCmd().table_name
        self.collect_model = DeviceCmd


# End File: kio/kio-server/modules/collections/device_cmds.py
