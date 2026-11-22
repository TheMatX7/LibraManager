from datetime import datetime, timezone
from sqlalchemy import select, func

from app.extensions import db
from app.models import Reservation
from app.repositories.base_repository import BaseRepository


class ReservationRepository(BaseRepository):

    def __init__(self):
        super().__init__(Reservation)

    def get_by_reader(self, reader_id):
        statement = select(Reservation).where(
            Reservation.reader_id == reader_id
        )
        return db.session.scalars(statement).all()

    def get_by_book(self, book_id):
        statement = select(Reservation).where(
            Reservation.book_id == book_id
        )
        return db.session.scalars(statement).all()

    def get_waiting_by_book(self, book_id):
        statement = select(Reservation).where(
            Reservation.book_id == book_id,
            Reservation.status == "WAITING"
        ).order_by(
            Reservation.reserved_at,
            Reservation.id
        )
        return db.session.scalars(statement).all()

    def get_active_by_reader(self, reader_id):
        statement = select(Reservation).where(
            Reservation.reader_id == reader_id,
            Reservation.status.in_(["WAITING", "READY"])
        )
        return db.session.scalars(statement).all()

    def count_active_by_reader(self, reader_id):
        statement = select(func.count()).select_from(
            Reservation
        ).where(
            Reservation.reader_id == reader_id,
            Reservation.status.in_(["WAITING", "READY"])
        )
        return db.session.scalar(statement)

    def get_expired_reservations(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        statement = select(Reservation).where(
            Reservation.status == "READY",
            Reservation.expires_at <= now
        )
        return db.session.scalars(statement).all()