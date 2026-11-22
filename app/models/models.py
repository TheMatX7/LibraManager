
from datetime import datetime, UTC
from app.extensions import db


# ==========================================
# 1. USERS - konta użytkowników
# ==========================================

def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)

class User(db.Model):
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="READER")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    reader = db.relationship(
        "Reader", back_populates="user", uselist=False
    )

    __table_args__ = (
    db.CheckConstraint(
        "role IN ('ADMIN', 'LIBRARIAN', 'READER')",
        name="check_user_role"
    ),
)


# ==========================================
# 2. READERS - dane czytelników
# ==========================================

class Reader(db.Model):
    __tablename__ = "readers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"),
        unique=True, nullable=False
    )
    card_number = db.Column(db.String(30), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30))
    registered_at = db.Column(db.DateTime, default=utc_now)

    user = db.relationship("User", back_populates="reader")
    loans = db.relationship("Loan", back_populates="reader")
    reservations = db.relationship(
        "Reservation", back_populates="reader"
    )
    __table_args__ = (
    db.CheckConstraint(
        "length(trim(first_name)) > 0",
        name="check_reader_first_name"
    ),
    db.CheckConstraint(
        "length(trim(last_name)) > 0",
        name="check_reader_last_name"
    ),
)


# ==========================================
# 3. CATEGORIES - kategorie książek
# ==========================================

class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)

    books = db.relationship("Book", back_populates="category")


# ==========================================
# 4. BOOKS - pozycje katalogowe
# ==========================================

class Book(db.Model):
    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), unique=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    publisher = db.Column(db.String(150))
    publication_year = db.Column(db.Integer)

    category_id = db.Column(
        db.Integer, db.ForeignKey("categories.id")
    )

    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    category = db.relationship("Category", back_populates="books")
    copies = db.relationship("Copy", back_populates="book")
    authors = db.relationship(
        "Author", secondary="book_authors",
        back_populates="books"
    )
    reservations = db.relationship(
        "Reservation", back_populates="book"
    )
    __table_args__ = (
    db.CheckConstraint(
        "publication_year IS NULL OR publication_year BETWEEN 1000 AND 2100",
        name="check_book_publication_year"
    ),
    db.CheckConstraint(
        "length(trim(title)) > 0",
        name="check_book_title"
    ),
)


# ==========================================
# 5. AUTHORS - autorzy
# ==========================================

class Author(db.Model):
    __tablename__ = "authors"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)

    books = db.relationship(
        "Book", secondary="book_authors",
        back_populates="authors"
    )


# ==========================================
# 6. BOOK_AUTHORS - relacja książek i autorów
# ==========================================

class BookAuthor(db.Model):
    __tablename__ = "book_authors"

    book_id = db.Column(
        db.Integer, db.ForeignKey("books.id"),
        primary_key=True
    )
    author_id = db.Column(
        db.Integer, db.ForeignKey("authors.id"),
        primary_key=True
    )


# ==========================================
# 7. COPIES - fizyczne egzemplarze
# ==========================================

class Copy(db.Model):
    __tablename__ = "copies"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(
        db.Integer, db.ForeignKey("books.id"), nullable=False
    )
    inventory_number = db.Column(
        db.String(50), unique=True, nullable=False
    )
    status = db.Column(
        db.String(20), default="AVAILABLE", nullable=False
    )
    added_at = db.Column(db.DateTime, default=utc_now)

    book = db.relationship("Book", back_populates="copies")
    loans = db.relationship("Loan", back_populates="copy")

    __table_args__ = (
    db.CheckConstraint(
        "status IN ('AVAILABLE', 'LOANED', 'RESERVED', 'DAMAGED', 'LOST')",
        name="check_copy_status"
    ),
)


# ==========================================
# 8. LOANS - wypożyczenia
# ==========================================

class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    copy_id = db.Column(
        db.Integer, db.ForeignKey("copies.id"), nullable=False
    )
    reader_id = db.Column(
        db.Integer, db.ForeignKey("readers.id"), nullable=False
    )

    borrowed_at = db.Column(db.DateTime, default=utc_now)
    due_date = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime)

    status = db.Column(
        db.String(20), default="ACTIVE", nullable=False
    )

    copy = db.relationship("Copy", back_populates="loans")
    reader = db.relationship("Reader", back_populates="loans")
    fine = db.relationship(
        "Fine", back_populates="loan", uselist=False
    )

    __table_args__ = (
    db.CheckConstraint(
        "status IN ('ACTIVE', 'RETURNED', 'CANCELLED')",
        name="check_loan_status"
    ),
)


# ==========================================
# 9. RESERVATIONS - rezerwacje
# ==========================================

class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(
        db.Integer, db.ForeignKey("books.id"), nullable=False
    )
    reader_id = db.Column(
        db.Integer, db.ForeignKey("readers.id"), nullable=False
    )

    reserved_at = db.Column(db.DateTime, default=utc_now)
    expires_at = db.Column(db.DateTime)
    status = db.Column(
        db.String(20), default="WAITING", nullable=False
    )

    book = db.relationship("Book", back_populates="reservations")
    reader = db.relationship(
        "Reader", back_populates="reservations"
    )

    __table_args__ = (
    db.CheckConstraint(
        "status IN ('WAITING', 'READY', 'FULFILLED', 'CANCELLED', 'EXPIRED')",
        name="check_reservation_status"
    ),
)


# ==========================================
# 10. FINES - kary
# ==========================================

class Fine(db.Model):
    __tablename__ = "fines"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(
        db.Integer, db.ForeignKey("loans.id"),
        unique=True, nullable=False
    )

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    paid_amount = db.Column(
        db.Numeric(10, 2), default=0, nullable=False
    )
    status = db.Column(
        db.String(20), default="UNPAID", nullable=False
    )
    created_at = db.Column(db.DateTime, default=utc_now)

    loan = db.relationship("Loan", back_populates="fine")
    payments = db.relationship("Payment", back_populates="fine")

    __table_args__ = (
    db.CheckConstraint(
        "amount >= 0",
        name="check_fine_amount"
    ),
    db.CheckConstraint(
        "paid_amount >= 0 AND paid_amount <= amount",
        name="check_fine_paid_amount"
    ),
    db.CheckConstraint(
        "status IN ('UNPAID', 'PARTIALLY_PAID', 'PAID')",
        name="check_fine_status"
    ),
)


# ==========================================
# 11. PAYMENTS - płatności
# ==========================================

class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    fine_id = db.Column(
        db.Integer, db.ForeignKey("fines.id"), nullable=False
    )

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False)
    paid_at = db.Column(db.DateTime, default=utc_now)

    fine = db.relationship("Fine", back_populates="payments")


    __table_args__ = (
    db.CheckConstraint(
        "amount > 0",
        name="check_payment_amount"
    ),
    db.CheckConstraint(
        "method IN ('CASH', 'CARD')",
        name="check_payment_method"
    ),
)


# ==========================================
# 12. AUDIT_LOGS - historia operacji
# ==========================================

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    user = db.relationship("User")


# ==========================================
# 13. SETTINGS - konfiguracja
# ==========================================

class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
