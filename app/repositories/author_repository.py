from sqlalchemy import select, or_

from app.extensions import db
from app.models import Author
from app.repositories.base_repository import BaseRepository


class AuthorRepository(BaseRepository):

    def __init__(self):
        super().__init__(Author)

    def get_by_name(self, first_name, last_name):
        statement = select(Author).where(
            Author.first_name == first_name,
            Author.last_name == last_name
        )

        return db.session.scalars(statement).all()

    def search(self, query):
        pattern = f"%{query}%"

        statement = select(Author).where(
            or_(
                Author.first_name.ilike(pattern),
                Author.last_name.ilike(pattern)
            )
        )

        return db.session.scalars(statement).all()