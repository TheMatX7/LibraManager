from sqlalchemy import select, or_

from app.extensions import db
from app.models import Book, Author
from app.repositories.base_repository import BaseRepository


class BookRepository(BaseRepository):

    def __init__(self):
        super().__init__(Book)

    def get_by_isbn(self, isbn):
        statement = select(Book).where(
            Book.isbn == isbn
        )
        return db.session.scalar(statement)

    def get_by_category(self, category_id):
        statement = select(Book).where(
            Book.category_id == category_id
        )
        return db.session.scalars(statement).all()

    def get_active_books(self):
        statement = select(Book).where(
            Book.is_archived.is_(False)
        )
        return db.session.scalars(statement).all()

    def get_archived_books(self):
        statement = select(Book).where(
            Book.is_archived.is_(True)
        )
        return db.session.scalars(statement).all()

    def search(self, query):
        pattern = f"%{query}%"

        statement = select(Book).where(
            Book.is_archived.is_(False),
            or_(
                Book.title.ilike(pattern),
                Book.isbn.ilike(pattern),
                Book.publisher.ilike(pattern),
                Book.authors.any(
                    or_(
                        Author.first_name.ilike(pattern),
                        Author.last_name.ilike(pattern)
                    )
                )
            )
        )

        return db.session.scalars(statement).all()