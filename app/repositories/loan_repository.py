from datetime import datetime, timezone
from sqlalchemy import select, func

from app.extensions import db
from app.models import Loan
from app.repositories.base_repository import BaseRepository


class LoanRepository(BaseRepository):

    def __init__(self):
        super().__init__(Loan)

    def get_by_reader(self, reader_id):
        statement = select(Loan).where(
            Loan.reader_id == reader_id
        )
        return db.session.scalars(statement).all()

    def get_by_copy(self, copy_id):
        statement = select(Loan).where(
            Loan.copy_id == copy_id
        )
        return db.session.scalars(statement).all()

    def get_active_loans(self):
        statement = select(Loan).where(
            Loan.status == "ACTIVE"
        )
        return db.session.scalars(statement).all()

    def get_active_by_reader(self, reader_id):
        statement = select(Loan).where(
            Loan.reader_id == reader_id,
            Loan.status == "ACTIVE"
        )
        return db.session.scalars(statement).all()

    def get_active_by_copy(self, copy_id):
        statement = select(Loan).where(
            Loan.copy_id == copy_id,
            Loan.status == "ACTIVE"
        )
        return db.session.scalars(statement).one_or_none()

    def count_active_by_reader(self, reader_id):
        statement = select(func.count()).select_from(
            Loan
        ).where(
            Loan.reader_id == reader_id,
            Loan.status == "ACTIVE"
        )
        return db.session.scalar(statement)

    def get_overdue_loans(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        statement = select(Loan).where(
            Loan.status == "ACTIVE",
            Loan.due_date < now
        )
        return db.session.scalars(statement).all()