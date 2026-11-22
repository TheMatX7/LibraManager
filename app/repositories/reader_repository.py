from sqlalchemy import select, or_

from app.extensions import db
from app.models import Reader
from app.repositories.base_repository import BaseRepository


class ReaderRepository(BaseRepository):

    def __init__(self):
        super().__init__(Reader)

    def get_by_card_number(self, card_number):
        statement = select(Reader).where(
            Reader.card_number == card_number
        )
        return db.session.scalar(statement)

    def get_by_user_id(self, user_id):
        statement = select(Reader).where(
            Reader.user_id == user_id
        )
        return db.session.scalar(statement)

    def search(self, query):
        pattern = f"%{query}%"

        statement = select(Reader).where(
            or_(
                Reader.first_name.ilike(pattern),
                Reader.last_name.ilike(pattern),
                Reader.card_number.ilike(pattern)
            )
        )

        return db.session.scalars(statement).all()