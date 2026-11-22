from sqlalchemy import select, func

from app.extensions import db


class BaseRepository:

    def __init__(self, model):
        self.model = model

    def get_by_id(self, record_id):
        return db.session.get(self.model, record_id)

    def get_all(self):
        statement = select(self.model)
        return db.session.scalars(statement).all()

    def add(self, instance):
        db.session.add(instance)
        return instance

    def delete(self, instance):
        db.session.delete(instance)

    def count(self):
        statement = select(func.count()).select_from(
            self.model
        )

        return db.session.scalar(statement)

    def exists(self, record_id):
        return self.get_by_id(record_id) is not None