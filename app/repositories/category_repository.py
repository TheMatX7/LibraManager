from sqlalchemy import select

from app.extensions import db
from app.models import Category
from app.repositories.base_repository import BaseRepository


class CategoryRepository(BaseRepository):

    def __init__(self):
        super().__init__(Category)

    def get_by_name(self, name):
        statement = select(Category).where(
            Category.name == name
        )

        return db.session.scalar(statement)

    def get_sorted(self):
        statement = select(Category).order_by(
            Category.name
        )

        return db.session.scalars(statement).all()