from sqlalchemy import select, func
from decimal import Decimal

from app.extensions import db
from app.models import Payment, Fine, Loan
from app.repositories.base_repository import BaseRepository


class PaymentRepository(BaseRepository):
    """Repository responsible for payment records."""

    def __init__(self):

        super().__init__(Payment)

    # ==========================================
    # PAYMENTS BY FINE
    # ==========================================

    def get_by_fine(self, fine_id):

        statement = select(Payment).where(
            Payment.fine_id == fine_id
        ).order_by(
            Payment.paid_at,
            Payment.id
        )

        return db.session.scalars(statement).all()

    # ==========================================
    # PAYMENTS BY METHOD
    # ==========================================

    def get_by_method(self, method):

        statement = select(Payment).where(
            Payment.method == method
        ).order_by(
            Payment.paid_at,
            Payment.id
        )

        return db.session.scalars(statement).all()

    def get_total_by_method(self, method):

        statement = select(
            func.sum(Payment.amount)
        ).where(
            Payment.method == method
        )

        result = db.session.scalar(statement)

        return (
            result
            if result is not None
            else Decimal("0.00")
        )

    # ==========================================
    # PAYMENTS BY READER
    # ==========================================

    def get_by_reader(self, reader_id):

        statement = (
            select(Payment)
            .join(
                Fine,
                Payment.fine_id == Fine.id
            )
            .join(
                Loan,
                Fine.loan_id == Loan.id
            )
            .where(
                Loan.reader_id == reader_id
            )
            .order_by(
                Payment.paid_at,
                Payment.id
            )
        )

        return db.session.scalars(statement).all()

    # ==========================================
    # TOTAL PAYMENTS BY FINE
    # ==========================================

    def get_total_by_fine(self, fine_id):

        statement = select(
            func.sum(Payment.amount)
        ).where(
            Payment.fine_id == fine_id
        )

        result = db.session.scalar(statement)

        return (
            result
            if result is not None
            else Decimal("0.00")
        )

    # ==========================================
    # TOTAL PAYMENTS BY READER
    # ==========================================

    def get_total_by_reader(self, reader_id):

        statement = (
            select(
                func.sum(Payment.amount)
            )
            .select_from(Payment)
            .join(
                Fine,
                Payment.fine_id == Fine.id
            )
            .join(
                Loan,
                Fine.loan_id == Loan.id
            )
            .where(
                Loan.reader_id == reader_id
            )
        )

        result = db.session.scalar(statement)

        return (
            result
            if result is not None
            else Decimal("0.00")
        )

    # ==========================================
    # TOTAL PAYMENTS
    # ==========================================

    def get_total_payments(self):

        statement = select(
            func.sum(Payment.amount)
        )

        result = db.session.scalar(statement)

        return (
            result
            if result is not None
            else Decimal("0.00")
        )
