from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db

from app.models import (
    User,
    Reader,
    Book,
    Author,
    Category,
    Copy,
    Loan,
    Reservation
)

from app.services import BookService, AuditService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    AuthorizationError,
    AuthenticationError,
    InactiveAccountError,
    NotFoundError,
    BusinessRuleError
)


ISBN13 = "9780132350884"
ISBN10 = "0132350882"


@pytest.fixture
def service(app):

    return BookService()


@pytest.fixture
def users(service):

    result = {}

    for role in ("ADMIN", "LIBRARIAN", "READER"):

        user = User(
            username=role.lower(),
            email=f"{role.lower()}@example.com",
            password_hash="test_hash",
            role=role,
            is_active=True
        )

        db.session.add(user)

        result[role.lower()] = user

    db.session.commit()

    return result


@pytest.fixture
def reader(users):

    reader = Reader(
        user_id=users["reader"].id,
        card_number="LIB-000001",
        first_name="Jan",
        last_name="Kowalski"
    )

    db.session.add(reader)
    db.session.commit()

    return reader


@pytest.fixture
def category(service):

    category = Category(name="Fantasy")

    db.session.add(category)
    db.session.commit()

    return category


@pytest.fixture
def author(service):

    author = Author(
        first_name="Andrzej",
        last_name="Sapkowski"
    )

    db.session.add(author)
    db.session.commit()

    return author


@pytest.fixture
def book(service, users, category, author):

    return service.create_book(
        actor_id=users["admin"].id,
        title="Wiedźmin",
        isbn=ISBN13,
        description="Test description",
        publisher="SuperNOWA",
        publication_year=1993,
        category_id=category.id,
        author_ids=[author.id]
    )


@pytest.fixture
def copy(book):

    copy = Copy(
        book_id=book.id,
        inventory_number="INV-001",
        status="AVAILABLE"
    )

    db.session.add(copy)
    db.session.commit()

    return copy


# ==========================================
# CREATION
# ==========================================


def test_create_book(book, category, author):

    assert book.id is not None
    assert book.title == "Wiedźmin"
    assert book.isbn == ISBN13
    assert book.category_id == category.id
    assert author in book.authors
    assert book.is_archived is False


def test_create_minimal_book(service, users):

    book = service.create_book(
        users["admin"].id,
        "Test Book"
    )

    assert book.id is not None
    assert book.isbn is None
    assert book.category is None
    assert book.authors == []


def test_create_without_isbn_twice(service, users):

    for title in ["Book One", "Book Two"]:

        service.create_book(
            users["admin"].id,
            title
        )

    assert service.count(users["admin"].id) == 2


def test_create_by_librarian(service, users):

    book = service.create_book(
        users["librarian"].id,
        "Test Book"
    )

    assert book.id is not None


def test_reader_cannot_create(service, users):

    with pytest.raises(AuthorizationError):

        service.create_book(
            users["reader"].id,
            "Test Book"
        )


def test_authentication_required(service):

    with pytest.raises(AuthenticationError):

        service.get_all(None)


def test_inactive_account(service, users):

    users["reader"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.get_all(users["reader"].id)


# ==========================================
# ISBN VALIDATION
# ==========================================


@pytest.mark.parametrize(
    "value",
    [
        ISBN13,
        ISBN10,
        "978-0-13-235088-4",
        "0-13-235088-2",
        " 9780132350884 ",
        "978 0 13 235088 4"
    ]
)
def test_valid_isbn(service, value):

    assert service.validate_isbn(value) == ISBN13


def test_isbn10_with_x(service):

    assert service.validate_isbn(
        "080442957X"
    ) == "9780804429573"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   "
    ]
)
def test_optional_isbn(service, value):

    assert service.validate_isbn(value) is None


@pytest.mark.parametrize(
    "value",
    [
        1234567890,
        True,
        "ABC",
        "123",
        "9780132350885",
        "0132350883",
        "978013235088X",
        "1234567890123",
        "97801323508844",
        "---"
    ]
)
def test_invalid_isbn(service, value):

    with pytest.raises(ValidationError):

        service.validate_isbn(value)


@pytest.mark.parametrize(
    "isbn",
    [
        ISBN10,
        ISBN13,
        "978-0-13-235088-4"
    ]
)
def test_duplicate_isbn(
    service, users, book, isbn
):

    with pytest.raises(DuplicateError):

        service.create_book(
            users["admin"].id,
            "Duplicate Book",
            isbn=isbn
        )


def test_archived_isbn_still_unique(
    service, users, book
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    with pytest.raises(DuplicateError):

        service.create_book(
            users["admin"].id,
            "Duplicate Book",
            isbn=ISBN13
        )


def test_legacy_isbn10_duplicate(service, users):

    old_book = Book(
        title="Legacy Book",
        isbn=ISBN10,
        is_archived=False
    )

    db.session.add(old_book)
    db.session.commit()

    with pytest.raises(DuplicateError):

        service.create_book(
            users["admin"].id,
            "New Book",
            isbn=ISBN13
        )


# ==========================================
# VALIDATION
# ==========================================


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        None,
        123,
        "A" * 201
    ]
)
def test_invalid_title(service, title):

    with pytest.raises(ValidationError):

        service.validate_title(title)


def test_title_max_length(service):

    assert service.validate_title(
        "A" * 200
    ) == "A" * 200


def test_title_whitespace(service):

    assert service.validate_title(
        "  Test Book  "
    ) == "Test Book"


@pytest.mark.parametrize(
    "year",
    [
        None,
        1000,
        1993,
        2026,
        2100
    ]
)
def test_valid_year(service, year):

    assert service.validate_publication_year(
        year
    ) == year


@pytest.mark.parametrize(
    "year",
    [
        999,
        2101,
        "2026",
        2026.5,
        True
    ]
)
def test_invalid_year(service, year):

    with pytest.raises(ValidationError):

        service.validate_publication_year(year)


@pytest.mark.parametrize(
    "field,value",
    [
        ("publisher", "A" * 151),
        ("publisher", 123),
        ("description", "A" * 10001),
        ("description", False)
    ]
)
def test_invalid_optional_text(
    service, users, field, value
):

    with pytest.raises(ValidationError):

        service.create_book(
            users["admin"].id,
            "Test Book",
            **{field: value}
        )


def test_optional_text_whitespace(service, users):

    book = service.create_book(
        users["admin"].id,
        "Test Book",
        description="   ",
        publisher="  Publisher  "
    )

    assert book.description is None
    assert book.publisher == "Publisher"


def test_nonexistent_category(service, users):

    with pytest.raises(NotFoundError):

        service.create_book(
            users["admin"].id,
            "Test Book",
            category_id=999999
        )


def test_nonexistent_author(service, users):

    with pytest.raises(NotFoundError):

        service.create_book(
            users["admin"].id,
            "Test Book",
            author_ids=[999999]
        )


@pytest.mark.parametrize(
    "value",
    [
        1,
        "1",
        True,
        [True],
        [0],
        [-1],
        ["1"]
    ]
)
def test_invalid_author_ids(
    service, users, value
):

    with pytest.raises(ValidationError):

        service.create_book(
            users["admin"].id,
            "Test Book",
            author_ids=value
        )


def test_duplicate_author(
    service, users, author
):

    with pytest.raises(ValidationError):

        service.create_book(
            users["admin"].id,
            "Test Book",
            author_ids=[
                author.id,
                author.id
            ]
        )


def test_multiple_authors(
    service, users, author
):

    second = Author(
        first_name="Jan",
        last_name="Nowak"
    )

    db.session.add(second)
    db.session.commit()

    book = service.create_book(
        users["admin"].id,
        "Collaborative Book",
        author_ids=[
            author.id,
            second.id
        ]
    )

    assert len(book.authors) == 2


# ==========================================
# READ
# ==========================================


def test_get_by_id(service, users, book):

    assert service.get_by_id(
        users["reader"].id,
        book.id
    ).id == book.id


def test_get_unknown_book(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["reader"].id,
            999999
        )


@pytest.mark.parametrize(
    "book_id",
    [None, True, 0, -1, "1"]
)
def test_invalid_book_id(
    service, users, book_id
):

    with pytest.raises(ValidationError):

        service.get_by_id(
            users["admin"].id,
            book_id
        )


@pytest.mark.parametrize(
    "isbn",
    [ISBN10, ISBN13, "978-0-13-235088-4"]
)
def test_get_by_isbn(
    service, users, book, isbn
):

    assert service.get_by_isbn(
        users["reader"].id,
        isbn
    ).id == book.id


def test_unknown_isbn(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_isbn(
            users["reader"].id,
            ISBN13
        )


def test_get_all(service, users, book):

    assert len(
        service.get_all(
            users["reader"].id
        )
    ) == 1


def test_get_by_category(
    service, users, book, category
):

    books = service.get_by_category(
        users["reader"].id,
        category.id
    )

    assert books == [book]


def test_get_by_author(
    service, users, book, author
):

    books = service.get_by_author(
        users["reader"].id,
        author.id
    )

    assert books == [book]


def test_count(service, users, book):

    assert service.count(
        users["reader"].id
    ) == 1


@pytest.mark.parametrize(
    "value",
    [None, 1, "true"]
)
def test_invalid_include_archived(
    service, users, value
):

    with pytest.raises(ValidationError):

        service.get_all(
            users["admin"].id,
            include_archived=value
        )


# ==========================================
# SEARCH
# ==========================================


@pytest.mark.parametrize(
    "query",
    [
        "Wiedźmin",
        "WIEDŹMIN",
        "wiedź",
        "Andrzej",
        "Sapkowski",
        "Andrzej Sapkowski",
        "Sapkowski Andrzej",
        "SuperNOWA",
        "Fantasy",
        ISBN13,
        ISBN10,
        "978-0-13-235088-4",
        "  wiedźmin  "
    ]
)
def test_search(
    service, users, book, query
):

    results = service.search(
        users["reader"].id,
        query
    )

    assert results == [book]


def test_search_no_results(
    service, users, book
):

    assert service.search(
        users["reader"].id,
        "Nonexistent"
    ) == []


@pytest.mark.parametrize(
    "query",
    ["", "   ", None, 123, "A" * 201]
)
def test_invalid_search(
    service, users, query
):

    with pytest.raises(ValidationError):

        service.search(
            users["reader"].id,
            query
        )


def test_search_sorted(service, users):

    for title in ["Zebra", "Alfa", "Beta"]:

        service.create_book(
            users["admin"].id,
            title
        )

    results = service.search(
        users["reader"].id,
        "a"
    )

    assert [
        book.title for book in results
    ] == [
        "Alfa", "Beta", "Zebra"
    ]


# ==========================================
# UPDATE
# ==========================================


def test_update_book(
    service, users, book, author, category
):

    result = service.update_book(
        users["admin"].id,
        book.id,
        "Updated Title",
        isbn=ISBN10,
        category_id=category.id,
        author_ids=[author.id]
    )

    assert result.title == "Updated Title"
    assert result.isbn == ISBN13
    assert result.category_id == category.id
    assert author in result.authors


def test_update_by_librarian(
    service, users, book
):

    service.update_book(
        users["librarian"].id,
        book.id,
        "Updated"
    )

    assert book.title == "Updated"


def test_reader_cannot_update(
    service, users, book
):

    with pytest.raises(AuthorizationError):

        service.update_book(
            users["reader"].id,
            book.id,
            "Updated"
        )


def test_update_duplicate_isbn(
    service, users, book
):

    second = service.create_book(
        users["admin"].id,
        "Second Book"
    )

    with pytest.raises(DuplicateError):

        service.update_book(
            users["admin"].id,
            second.id,
            "Second Book",
            isbn=ISBN13
        )


def test_invalid_update_preserves_data(
    service, users, book
):

    with pytest.raises(ValidationError):

        service.update_book(
            users["admin"].id,
            book.id,
            "",
            publication_year=999
        )

    assert book.title == "Wiedźmin"
    assert book.isbn == ISBN13


def test_update_preserves_copies(
    service, users, book, copy
):

    service.update_book(
        users["admin"].id,
        book.id,
        "Updated"
    )

    assert copy in book.copies


def test_update_removes_optional_fields(
    service, users, book
):

    service.update_book(
        users["admin"].id,
        book.id,
        book.title
    )

    assert book.isbn is None
    assert book.publisher is None
    assert book.category is None
    assert book.authors == []


# ==========================================
# ARCHIVING
# ==========================================


def test_archive_book(service, users, book):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    assert book.is_archived is True

    assert service.repository.get_by_id(
        book.id
    ) is not None


def test_archive_by_librarian(
    service, users, book
):

    service.archive_book(
        users["librarian"].id,
        book.id
    )

    assert book.is_archived is True


def test_reader_cannot_archive(
    service, users, book
):

    with pytest.raises(AuthorizationError):

        service.archive_book(
            users["reader"].id,
            book.id
        )


def test_restore_book(service, users, book):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    service.restore_book(
        users["admin"].id,
        book.id
    )

    assert book.is_archived is False


def test_reader_cannot_restore(
    service, users, book
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    with pytest.raises(AuthorizationError):

        service.restore_book(
            users["reader"].id,
            book.id
        )


def test_archiving_is_idempotent(
    service, users, book
):

    for _ in range(2):

        service.archive_book(
            users["admin"].id,
            book.id
        )

    logs = AuditService().get_by_action(
        "BOOK_ARCHIVED"
    )

    assert len(logs) == 1


def test_restoring_is_idempotent(
    service, users, book
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    for _ in range(2):

        service.restore_book(
            users["admin"].id,
            book.id
        )

    logs = AuditService().get_by_action(
        "BOOK_RESTORED"
    )

    assert len(logs) == 1


def test_archived_book_hidden(
    service, users, book, author, category
):

    actor = users["reader"].id

    service.archive_book(
        users["admin"].id,
        book.id
    )

    assert service.get_all(actor) == []
    assert service.search(actor, "Wiedźmin") == []
    assert service.count(actor) == 0

    assert service.get_by_author(
        actor,
        author.id
    ) == []

    assert service.get_by_category(
        actor,
        category.id
    ) == []

    with pytest.raises(NotFoundError):

        service.get_by_id(actor, book.id)

    with pytest.raises(NotFoundError):

        service.get_by_isbn(actor, ISBN13)


def test_staff_archive_access(
    service, users, book
):

    actor = users["admin"].id

    service.archive_book(actor, book.id)

    assert service.get_archived_books(
        actor
    ) == [book]

    assert service.get_all(
        actor,
        include_archived=True
    ) == [book]

    assert service.get_by_id(
        actor,
        book.id,
        include_archived=True
    ) == book


def test_reader_cannot_access_archive(
    service, users
):

    actor = users["reader"].id

    with pytest.raises(AuthorizationError):

        service.get_archived_books(actor)

    with pytest.raises(AuthorizationError):

        service.get_all(
            actor,
            include_archived=True
        )


def test_cannot_edit_archived_book(
    service, users, book
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    with pytest.raises(BusinessRuleError):

        service.update_book(
            users["admin"].id,
            book.id,
            "Updated Title"
        )


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED"]
)
def test_archive_blocked_by_copy_status(
    service, users, book, copy, status
):

    copy.status = status
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.archive_book(
            users["admin"].id,
            book.id
        )

    assert book.is_archived is False


@pytest.mark.parametrize(
    "status",
    ["AVAILABLE", "DAMAGED", "LOST"]
)
def test_archive_allowed_by_copy_status(
    service, users, book, copy, status
):

    copy.status = status
    db.session.commit()

    service.archive_book(
        users["admin"].id,
        book.id
    )

    assert book.is_archived is True
    assert copy.book_id == book.id
    assert copy.status == status


def test_archive_blocked_by_active_loan(
    service, users, book, copy, reader
):

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    loan = Loan(
        copy_id=copy.id,
        reader_id=reader.id,
        borrowed_at=now,
        due_date=now + timedelta(days=30),
        status="ACTIVE"
    )

    db.session.add(loan)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.archive_book(
            users["admin"].id,
            book.id
        )

    assert book.is_archived is False


def test_archive_allowed_after_return(
    service, users, book, copy, reader
):

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    loan = Loan(
        copy_id=copy.id,
        reader_id=reader.id,
        borrowed_at=now - timedelta(days=5),
        due_date=now + timedelta(days=25),
        returned_at=now,
        status="RETURNED"
    )

    db.session.add(loan)
    db.session.commit()

    service.archive_book(
        users["admin"].id,
        book.id
    )

    assert book.is_archived is True

    assert db.session.get(
        Loan, loan.id
    ) is not None


@pytest.mark.parametrize(
    "status",
    ["WAITING", "READY"]
)
def test_archive_blocked_by_reservation(
    service, users, book, reader, status
):

    reservation = Reservation(
        book_id=book.id,
        reader_id=reader.id,
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.archive_book(
            users["admin"].id,
            book.id
        )

    assert book.is_archived is False


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_archive_allowed_by_reservation(
    service, users, book, reader, status
):

    reservation = Reservation(
        book_id=book.id,
        reader_id=reader.id,
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    service.archive_book(
        users["admin"].id,
        book.id
    )

    assert book.is_archived is True

    assert db.session.get(
        Reservation,
        reservation.id
    ) is not None


# ==========================================
# AVAILABILITY
# ==========================================


def test_availability_without_copies(
    service, users, book
):

    result = service.get_availability(
        users["reader"].id,
        book.id
    )

    assert result["total"] == 0
    assert result["available"] == 0
    assert result["is_available"] is False


def test_availability_with_copies(
    service, users, book
):

    statuses = [
        "AVAILABLE",
        "AVAILABLE",
        "LOANED",
        "RESERVED",
        "DAMAGED",
        "LOST"
    ]

    for index, status in enumerate(statuses):

        db.session.add(
            Copy(
                book_id=book.id,
                inventory_number=f"INV-{index}",
                status=status
            )
        )

    db.session.commit()

    result = service.get_availability(
        users["reader"].id,
        book.id
    )

    assert result["total"] == 6
    assert result["available"] == 2
    assert result["loaned"] == 1
    assert result["reserved"] == 1
    assert result["damaged"] == 1
    assert result["lost"] == 1
    assert result["is_available"] is True


def test_no_available_copies(
    service, users, book, copy
):

    copy.status = "LOANED"
    db.session.commit()

    result = service.get_availability(
        users["reader"].id,
        book.id
    )

    assert result["available"] == 0
    assert result["is_available"] is False


def test_archived_availability_hidden(
    service, users, book
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    with pytest.raises(NotFoundError):

        service.get_availability(
            users["reader"].id,
            book.id
        )


# ==========================================
# AUDIT
# ==========================================


def test_creation_audit(book):

    logs = AuditService().get_by_action(
        "BOOK_CREATED"
    )

    assert len(logs) == 1


def test_update_audit(service, users, book):

    service.update_book(
        users["admin"].id,
        book.id,
        "Updated"
    )

    logs = AuditService().get_by_action(
        "BOOK_UPDATED"
    )

    assert len(logs) == 1


def test_archive_audit(service, users, book):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    logs = AuditService().get_by_action(
        "BOOK_ARCHIVED"
    )

    assert len(logs) == 1


def test_restore_audit(service, users, book):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    service.restore_book(
        users["admin"].id,
        book.id
    )

    logs = AuditService().get_by_action(
        "BOOK_RESTORED"
    )

    assert len(logs) == 1


# ==========================================
# TRANSACTIONS
# ==========================================


def fail_audit(*args, **kwargs):

    raise BusinessRuleError(
        "Simulated audit failure"
    )


def test_create_rollback(
    service, users, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.create_book(
            users["admin"].id,
            "Test Book"
        )

    assert service.repository.count() == 0


def test_update_rollback(
    service, users, book, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.update_book(
            users["admin"].id,
            book.id,
            "Updated"
        )

    assert book.title == "Wiedźmin"
    assert book.isbn == ISBN13
    assert len(book.authors) == 1


def test_archive_rollback(
    service, users, book, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.archive_book(
            users["admin"].id,
            book.id
        )

    assert book.is_archived is False


def test_restore_rollback(
    service, users, book, monkeypatch
):

    service.archive_book(
        users["admin"].id,
        book.id
    )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.restore_book(
            users["admin"].id,
            book.id
        )

    assert book.is_archived is True