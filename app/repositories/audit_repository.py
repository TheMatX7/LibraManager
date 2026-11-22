from sqlalchemy import select

from app.extensions import db
from app.models import AuditLog
from app.repositories.base_repository import BaseRepository


class AuditRepository(BaseRepository):

    def __init__(self):
        super().__init__(AuditLog)

    def get_by_user(self, user_id):
        statement = select(AuditLog).where(
            AuditLog.user_id == user_id
        ).order_by(AuditLog.created_at.desc())

        return db.session.scalars(statement).all()

    def get_by_action(self, action):
        statement = select(AuditLog).where(
            AuditLog.action == action
        )
        return db.session.scalars(statement).all()

    def get_recent(self, limit=50):
        statement = select(AuditLog).order_by(
            AuditLog.created_at.desc(),
            AuditLog.id.desc()
        ).limit(limit)

        return db.session.scalars(statement).all()