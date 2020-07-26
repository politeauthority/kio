"""Devices Collection
Gets collections of devices.

"""
from .base import Base
from ..models.device import Device


class Devices(Base):
    """Collection class for gathering groups of devices."""

    def __init__(self, conn=None, cursor=None):
        """Store Sqlite conn and model table_name as well as the model obj for the collections
           target model.
        """
        super(Devices, self).__init__(conn, cursor)
        self.table_name = Device().table_name
        self.collect_model = Device


# End File: kio/kio-server/modules/collections/devices.py
