from sqlalchemy import select, func

from app.extensions import db
from app.models import Copy
from app.repositories.base_repository import BaseRepository


class CopyRepository(BaseRepository):

    def __init__(self):
        super().__init__(Copy)

    def get_by_inventory_number(self, inventory_number):
        statement = select(Copy).where(
            Copy.inventory_number == inventory_number
        )

        return db.session.scalar(statement)

    def get_by_book_id(self, book_id):
        statement = select(Copy).where(
            Copy.book_id == book_id
        )

        return db.session.scalars(statement).all()

    def get_by_status(self, status):
        statement = select(Copy).where(
            Copy.status == status
        )

        return db.session.scalars(statement).all()

    def get_available_copies(self, book_id):
        statement = select(Copy).where(
            Copy.book_id == book_id,
            Copy.status == "AVAILABLE"
        )

        return db.session.scalars(statement).all()

    def count_available_copies(self, book_id):
        statement = select(func.count()).select_from(
            Copy
        ).where(
            Copy.book_id == book_id,
            Copy.status == "AVAILABLE"
        )

        return db.session.scalar(statement)