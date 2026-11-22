from sqlalchemy import select

from app.extensions import db
from app.models import User
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):

    def __init__(self):
        super().__init__(User)

    def get_by_username(self, username):
        statement = select(User).where(
            User.username == username
        )
        return db.session.scalar(statement)

    def get_by_email(self, email):
        statement = select(User).where(
            User.email == email
        )
        return db.session.scalar(statement)

    def get_by_role(self, role):
        statement = select(User).where(
            User.role == role
        )
        return db.session.scalars(statement).all()

    def get_active_users(self):
        statement = select(User).where(
            User.is_active.is_(True)
        )
        return db.session.scalars(statement).all()

    def get_inactive_users(self):
        statement = select(User).where(
            User.is_active.is_(False)
        )
        return db.session.scalars(statement).all()