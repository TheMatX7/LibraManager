import re
import unicodedata

from app.extensions import db
from app.models import Book

from app.repositories import (
    BookRepository,
    AuthorRepository,
    CategoryRepository,
    CopyRepository,
    LoanRepository,
    ReservationRepository
)

from app.services.base_service import BaseService
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    BusinessRuleError,
    NotFoundError
)


class BookService(BaseService):
    """Service responsible for the library book catalogue."""

    COPY_STATUSES = (
        "AVAILABLE",
        "LOANED",
        "RESERVED",
        "DAMAGED",
        "LOST"
    )

    def __init__(self):

        self.repository = BookRepository()
        self.author_repository = AuthorRepository()
        self.category_repository = CategoryRepository()
        self.copy_repository = CopyRepository()
        self.loan_repository = LoanRepository()
        self.reservation_repository = ReservationRepository()

        self.auth_service = AuthService()
        self.audit_service = AuditService()

    # ==========================================
    # VALIDATION
    # ==========================================

    @staticmethod
    def normalize_text(value):

        return unicodedata.normalize(
            "NFC", value.strip()
        ).casefold()

    def validate_title(self, title):

        title = self.require_text(title, "Title")

        title = unicodedata.normalize("NFC", title)

        if len(title) > 200:

            raise ValidationError(
                "Title cannot exceed 200 characters."
            )

        return title

    def validate_optional_text(
        self,
        value,
        field_name,
        max_length
    ):

        if value is None:

            return None

        if not isinstance(value, str):

            raise ValidationError(
                f"{field_name} must be a string."
            )

        value = unicodedata.normalize(
            "NFC", value.strip()
        )

        if not value:

            return None

        if len(value) > max_length:

            raise ValidationError(
                f"{field_name} is too long."
            )

        return value

    def validate_publication_year(self, year):

        if year is None:

            return None

        if type(year) is not int:

            raise ValidationError(
                "Publication year must be an integer."
            )

        if not 1000 <= year <= 2100:

            raise ValidationError(
                "Publication year must be between 1000 and 2100."
            )

        return year

    @staticmethod
    def isbn13_check_digit(value):

        total = sum(
            int(digit) * (1 if index % 2 == 0 else 3)
            for index, digit in enumerate(value)
        )

        return str((10 - total % 10) % 10)

    def validate_isbn(self, isbn):

        if isbn is None:

            return None

        if not isinstance(isbn, str):

            raise ValidationError(
                "ISBN must be a string."
            )

        isbn = isbn.strip()

        if not isbn:

            return None

        isbn = re.sub(
            r"[\s-]", "", isbn
        ).upper()

        # ISBN-10

        if re.fullmatch(r"[0-9]{9}[0-9X]", isbn):

            digits = [
                10 if digit == "X" else int(digit)
                for digit in isbn
            ]

            checksum = sum(
                digit * (10 - index)
                for index, digit in enumerate(digits)
            )

            if checksum % 11 != 0:

                raise ValidationError(
                    "Invalid ISBN-10 checksum."
                )

            prefix = "978" + isbn[:9]

            return prefix + self.isbn13_check_digit(
                prefix
            )

        # ISBN-13

        if re.fullmatch(
            r"(978|979)[0-9]{10}", isbn
        ):

            expected = self.isbn13_check_digit(
                isbn[:12]
            )

            if isbn[-1] != expected:

                raise ValidationError(
                    "Invalid ISBN-13 checksum."
                )

            return isbn

        raise ValidationError(
            "Invalid ISBN format."
        )

    def validate_id(self, value, field_name):

        if type(value) is not int or value < 1:

            raise ValidationError(
                f"Invalid {field_name} identifier."
            )

        return value

    def validate_category(self, category_id):

        if category_id is None:

            return None

        self.validate_id(category_id, "category")

        return self.require_exists(
            self.category_repository.get_by_id(
                category_id
            ),
            "Category not found."
        )

    def validate_authors(self, author_ids):

        if author_ids is None:

            return []

        if not isinstance(
            author_ids, (list, tuple)
        ):

            raise ValidationError(
                "Author identifiers must be a list or tuple."
            )

        authors = []
        seen = set()

        for author_id in author_ids:

            self.validate_id(
                author_id, "author"
            )

            if author_id in seen:

                raise ValidationError(
                    "Duplicate author identifier."
                )

            author = self.require_exists(
                self.author_repository.get_by_id(
                    author_id
                ),
                "Author not found."
            )

            authors.append(author)
            seen.add(author_id)

        return authors

    # ==========================================
    # INTERNAL METHODS
    # ==========================================

    def _get_book(self, book_id):

        self.validate_id(book_id, "book")

        return self.require_exists(
            self.repository.get_by_id(book_id),
            "Book not found."
        )

    def _find_isbn(self, isbn):

        if isbn is None:

            return None

        # Supports older ISBN-10 records and
        # formatted ISBN values.

        matches = []

        for book in self.repository.get_all():

            if book.isbn is None:

                continue

            try:

                normalized = self.validate_isbn(
                    book.isbn
                )

            except ValidationError:

                continue

            if normalized == isbn:

                matches.append(book)

        if len(matches) > 1:

            raise BusinessRuleError(
                "Multiple books have equivalent ISBN numbers."
            )

        return matches[0] if matches else None

    def _check_duplicate_isbn(
        self,
        isbn,
        exclude_id=None
    ):

        if isbn is None:

            return

        existing = self._find_isbn(isbn)

        if (
            existing is not None
            and existing.id != exclude_id
        ):

            raise DuplicateError(
                "ISBN already exists."
            )

    def _require_archive_access(
        self,
        actor_id,
        include_archived
    ):

        self.auth_service.get_current_user(
            actor_id
        )

        if type(include_archived) is not bool:

            raise ValidationError(
                "Include archived must be a boolean."
            )

        if include_archived:

            self.auth_service.require_staff(
                actor_id
            )

    def _validate_book_data(
        self,
        title,
        isbn,
        description,
        publisher,
        publication_year,
        category_id,
        author_ids
    ):

        title = self.validate_title(title)

        isbn = self.validate_isbn(isbn)

        description = self.validate_optional_text(
            description,
            "Description",
            10000
        )

        publisher = self.validate_optional_text(
            publisher,
            "Publisher",
            150
        )

        publication_year = (
            self.validate_publication_year(
                publication_year
            )
        )

        category = self.validate_category(
            category_id
        )

        authors = self.validate_authors(
            author_ids
        )

        return {
            "title": title,
            "isbn": isbn,
            "description": description,
            "publisher": publisher,
            "publication_year": publication_year,
            "category": category,
            "authors": authors
        }

    # ==========================================
    # CREATE
    # ==========================================

    def create_book(
        self,
        actor_id,
        title,
        isbn=None,
        description=None,
        publisher=None,
        publication_year=None,
        category_id=None,
        author_ids=None
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            data = self._validate_book_data(
                title,
                isbn,
                description,
                publisher,
                publication_year,
                category_id,
                author_ids
            )

            self._check_duplicate_isbn(
                data["isbn"]
            )

            book = Book(
                **data,
                is_archived=False
            )

            self.repository.add(book)

            db.session.flush()

            self.audit_service.log(
                action="BOOK_CREATED",
                user_id=actor_id,
                description=(
                    f"Created book ID: {book.id}"
                )
            )

        return book

    # ==========================================
    # READ
    # ==========================================

    def get_by_id(
        self,
        actor_id,
        book_id,
        include_archived=False
    ):

        self._require_archive_access(
            actor_id,
            include_archived
        )

        book = self._get_book(book_id)

        if book.is_archived and not include_archived:

            raise NotFoundError(
                "Book not found."
            )

        return book

    def get_by_isbn(
        self,
        actor_id,
        isbn,
        include_archived=False
    ):

        self._require_archive_access(
            actor_id,
            include_archived
        )

        isbn = self.validate_isbn(isbn)

        if isbn is None:

            raise ValidationError(
                "ISBN is required."
            )

        book = self._find_isbn(isbn)

        if book is None:

            raise NotFoundError(
                "Book not found."
            )

        if book.is_archived and not include_archived:

            raise NotFoundError(
                "Book not found."
            )

        return book

    def get_all(
        self,
        actor_id,
        include_archived=False
    ):

        self._require_archive_access(
            actor_id,
            include_archived
        )

        if include_archived:

            return self.repository.get_all()

        return self.repository.get_active_books()

    def get_archived_books(self, actor_id):

        self.auth_service.require_staff(
            actor_id
        )

        return self.repository.get_archived_books()

    def get_by_category(
        self,
        actor_id,
        category_id,
        include_archived=False
    ):

        self._require_archive_access(
            actor_id,
            include_archived
        )

        self.validate_id(
            category_id, "category"
        )

        self.validate_category(category_id)

        books = self.repository.get_by_category(
            category_id
        )

        if include_archived:

            return books

        return [
            book for book in books
            if not book.is_archived
        ]

    def get_by_author(
        self,
        actor_id,
        author_id,
        include_archived=False
    ):

        self._require_archive_access(
            actor_id,
            include_archived
        )

        self.validate_id(author_id, "author")

        author = self.require_exists(
            self.author_repository.get_by_id(
                author_id
            ),
            "Author not found."
        )

        if include_archived:

            return list(author.books)

        return [
            book for book in author.books
            if not book.is_archived
        ]

    # ==========================================
    # SEARCH
    # ==========================================

    def search(
        self,
        actor_id,
        query,
        include_archived=False
    ):

        books = self.get_all(
            actor_id,
            include_archived
        )

        query = self.require_text(
            query, "Search query"
        )

        if len(query) > 200:

            raise ValidationError(
                "Search query is too long."
            )

        query = self.normalize_text(query)

        try:

            query_isbn = self.validate_isbn(
                query
            )

        except ValidationError:

            query_isbn = None

        results = []

        for book in books:

            fields = [
                book.title,
                book.isbn or "",
                book.publisher or ""
            ]

            if book.category is not None:

                fields.append(book.category.name)

            for author in book.authors:

                fields.extend([
                    f"{author.first_name} {author.last_name}",
                    f"{author.last_name} {author.first_name}"
                ])

            matched = any(
                query in self.normalize_text(value)
                for value in fields
            )

            if query_isbn and book.isbn:

                try:

                    matched = matched or (
                        self.validate_isbn(book.isbn)
                        == query_isbn
                    )

                except ValidationError:

                    pass

            if matched:

                results.append(book)

        return sorted(
            results,
            key=lambda book: (
                self.normalize_text(book.title),
                book.id
            )
        )

    # ==========================================
    # UPDATE
    # ==========================================

    def update_book(
        self,
        actor_id,
        book_id,
        title,
        isbn=None,
        description=None,
        publisher=None,
        publication_year=None,
        category_id=None,
        author_ids=None
    ):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            book = self._get_book(book_id)

            if book.is_archived:

                raise BusinessRuleError(
                    "Restore the book before editing."
                )

            data = self._validate_book_data(
                title,
                isbn,
                description,
                publisher,
                publication_year,
                category_id,
                author_ids
            )

            self._check_duplicate_isbn(
                data["isbn"],
                exclude_id=book.id
            )

            for field, value in data.items():

                setattr(book, field, value)

            self.audit_service.log(
                action="BOOK_UPDATED",
                user_id=actor_id,
                description=(
                    f"Updated book ID: {book.id}"
                )
            )

        return book

    # ==========================================
    # ARCHIVING
    # ==========================================

    def archive_book(self, actor_id, book_id):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            book = self._get_book(book_id)

            if book.is_archived:

                return book

            copies = self.copy_repository.get_by_book_id(
                book.id
            )

            for copy in copies:

                if copy.status in (
                    "LOANED", "RESERVED"
                ):

                    raise BusinessRuleError(
                        "Book has loaned or reserved copies."
                    )

                loans = self.loan_repository.get_by_copy(
                    copy.id
                )

                if any(
                    loan.status == "ACTIVE"
                    for loan in loans
                ):

                    raise BusinessRuleError(
                        "Book has active loans."
                    )

            reservations = (
                self.reservation_repository.get_by_book(
                    book.id
                )
            )

            if any(
                reservation.status in (
                    "WAITING", "READY"
                )
                for reservation in reservations
            ):

                raise BusinessRuleError(
                    "Book has active reservations."
                )

            book.is_archived = True

            self.audit_service.log(
                action="BOOK_ARCHIVED",
                user_id=actor_id,
                description=(
                    f"Archived book ID: {book.id}"
                )
            )

        return book

    def restore_book(self, actor_id, book_id):

        with self.transaction():

            self.auth_service.require_staff(
                actor_id
            )

            book = self._get_book(book_id)

            if not book.is_archived:

                return book

            book.is_archived = False

            self.audit_service.log(
                action="BOOK_RESTORED",
                user_id=actor_id,
                description=(
                    f"Restored book ID: {book.id}"
                )
            )

        return book

    # ==========================================
    # AVAILABILITY
    # ==========================================

    def get_availability(
        self,
        actor_id,
        book_id
    ):

        book = self.get_by_id(
            actor_id,
            book_id
        )

        copies = self.copy_repository.get_by_book_id(
            book.id
        )

        statuses = {
            status: 0
            for status in self.COPY_STATUSES
        }

        for copy in copies:

            statuses[copy.status] += 1

        return {
            "book_id": book.id,
            "total": len(copies),
            "available": statuses["AVAILABLE"],
            "loaned": statuses["LOANED"],
            "reserved": statuses["RESERVED"],
            "damaged": statuses["DAMAGED"],
            "lost": statuses["LOST"],
            "is_available": statuses["AVAILABLE"] > 0
        }

    def count(
        self,
        actor_id,
        include_archived=False
    ):

        return len(
            self.get_all(
                actor_id,
                include_archived
            )
        )