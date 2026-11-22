from sqlalchemy import select

from app.extensions import db
from app.models import Setting
from app.repositories.base_repository import BaseRepository


class SettingRepository(BaseRepository):

    def __init__(self):
        super().__init__(Setting)

    def get_by_key(self, key):
        statement = select(Setting).where(
            Setting.key == key
        )
        return db.session.scalar(statement)

    def get_value(self, key, default=None):
        setting = self.get_by_key(key)

        if setting is None:
            return default

        return setting.value

    def set_value(self, key, value, description=None):
        setting = self.get_by_key(key)

        if setting is None:
            setting = Setting(
                key=key,
                value=str(value),
                description=description
            )
            db.session.add(setting)

        else:
            setting.value = str(value)

            if description is not None:
                setting.description = description

        db.session.flush()

        return setting