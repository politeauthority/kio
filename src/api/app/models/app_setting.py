from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    """Global key/value store for non-boolean app settings.

    Boolean feature toggles live in `feature_flags`; this table holds the
    richer settings (ints, etc.) such as the agent heartbeat/checkin tuning.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=True)
