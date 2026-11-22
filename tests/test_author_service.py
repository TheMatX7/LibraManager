import pytest

from app.extensions import db
from app.models import User, Author, Book

from app.services import (
    AuthorService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    AuthorizationError,
    AuthenticationError,
    BusinessRuleError,
    NotFoundError,
    InactiveAccountError
)


@pytest.fixture
def service(app):

    return AuthorService()


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
def author(service, users):

    return service.create_author(
        users["admin"].id,
        "Andrzej",
        "Sapkowski"
    )


@pytest.fixture
def author_books(author):

    active_book = Book(
        title="Ostatnie życzenie",
        is_archived=False
    )

    archived_book = Book(
        title="Miecz przeznaczenia",
        is_archived=True
    )

    active_book.authors.append(author)
    archived_book.authors.append(author)

    db.session.add_all([
        active_book,
        archived_book
    ])

    db.session.commit()

    return {
        "active": active_book,
        "archived": archived_book
    }


# CREATION


def test_create_author(author):

    assert author.id is not None
    assert author.first_name == "Andrzej"
    assert author.last_name == "Sapkowski"


def test_create_by_librarian(service, users):

    author = service.create_author(
        users["librarian"].id,
        "Stephen",
        "King"
    )

    assert author.id is not None


def test_reader_cannot_create_author(service, users):

    with pytest.raises(AuthorizationError):

        service.create_author(
            users["reader"].id,
            "Stephen",
            "King"
        )


def test_authentication_required(service):

    with pytest.raises(AuthenticationError):

        service.get_all(None)


def test_inactive_user_denied(service, users):

    users["reader"].is_active = False

    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.get_all(
            users["reader"].id
        )


def test_duplicate_names_allowed(
    service, users, author
):

    second = service.create_author(
        users["admin"].id,
        "Andrzej",
        "Sapkowski"
    )

    assert second.id != author.id

    assert service.count(
        users["admin"].id
    ) == 2


# VALIDATION


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        None,
        123,
        "123",
        "Jan123",
        "---",
        "...",
        "A" * 101
    ]
)
def test_invalid_name(service, name):

    with pytest.raises(ValidationError):

        service.validate_name(
            name,
            "First name"
        )


@pytest.mark.parametrize(
    "name",
    [
        "Łukasz",
        "Stanisław",
        "Jean-Paul",
        "O'Connor",
        "O’Connor",
        "J. R. R.",
        "Maria Anna",
        "Kowalska-Nowak",
        "A" * 100
    ]
)
def test_valid_name(service, name):

    assert service.validate_name(
        name,
        "Name"
    ) == name


def test_name_whitespace(service):

    assert service.validate_name(
        "  Andrzej  ",
        "First name"
    ) == "Andrzej"


def test_unicode_normalization(service):

    assert service.validate_name(
        "Z\u0307aneta",
        "First name"
    ) == "Żaneta"


# READ OPERATIONS


def test_get_by_id(service, users, author):

    result = service.get_by_id(
        users["reader"].id,
        author.id
    )

    assert result.id == author.id


def test_get_nonexistent_author(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["admin"].id,
            999999
        )


def test_get_all_authors(service, users, author):

    result = service.get_all(
        users["reader"].id
    )

    assert len(result) == 1


def test_get_by_name(service, users, author):

    result = service.get_by_name(
        users["reader"].id,
        "ANDRZEJ",
        "SAPKOWSKI"
    )

    assert len(result) == 1
    assert result[0].id == author.id


def test_get_multiple_matching_authors(
    service, users, author
):

    service.create_author(
        users["admin"].id,
        "Andrzej",
        "Sapkowski"
    )

    result = service.get_by_name(
        users["reader"].id,
        "Andrzej",
        "Sapkowski"
    )

    assert len(result) == 2


def test_get_by_unknown_name(service, users):

    result = service.get_by_name(
        users["reader"].id,
        "Jan",
        "Nowak"
    )

    assert result == []


def test_count_authors(service, users, author):

    assert service.count(
        users["reader"].id
    ) == 1


def test_sorted_authors(service, users):

    for first_name, last_name in [
        ("Andrzej", "Sapkowski"),
        ("Stephen", "King"),
        ("Stanisław", "Lem")
    ]:

        service.create_author(
            users["admin"].id,
            first_name,
            last_name
        )

    result = service.get_sorted(
        users["reader"].id
    )

    assert [
        item.last_name for item in result
    ] == [
        "King",
        "Lem",
        "Sapkowski"
    ]


def test_sorted_same_last_name(service, users):

    for first_name in ["Jan", "Adam"]:

        service.create_author(
            users["admin"].id,
            first_name,
            "Kowalski"
        )

    result = service.get_sorted(
        users["reader"].id
    )

    assert [
        item.first_name for item in result
    ] == ["Adam", "Jan"]


# SEARCH


@pytest.mark.parametrize(
    "query",
    [
        "Andrzej",
        "Sapkowski",
        "sapk",
        "ANDRZEJ SAPKOWSKI",
        "Sapkowski Andrzej",
        "  sapkowski  "
    ]
)
def test_search_author(
    service, users, author, query
):

    result = service.search(
        users["reader"].id,
        query
    )

    assert len(result) == 1
    assert result[0].id == author.id


def test_unicode_search(service, users):

    service.create_author(
        users["admin"].id,
        "Łukasz",
        "Orbitowski"
    )

    result = service.search(
        users["reader"].id,
        "ŁUKASZ"
    )

    assert len(result) == 1


def test_search_no_results(service, users, author):

    result = service.search(
        users["reader"].id,
        "Nonexistent"
    )

    assert result == []


@pytest.mark.parametrize(
    "query",
    ["", "   ", None, 123, "A" * 202]
)
def test_invalid_search(service, users, query):

    with pytest.raises(ValidationError):

        service.search(
            users["reader"].id,
            query
        )


# UPDATE


def test_update_author(service, users, author):

    service.update_author(
        users["admin"].id,
        author.id,
        "Adam",
        "Nowak"
    )

    assert author.first_name == "Adam"
    assert author.last_name == "Nowak"


def test_update_by_librarian(
    service, users, author
):

    service.update_author(
        users["librarian"].id,
        author.id,
        "Jan",
        "Kowalski"
    )

    assert author.first_name == "Jan"


def test_reader_cannot_update(
    service, users, author
):

    with pytest.raises(AuthorizationError):

        service.update_author(
            users["reader"].id,
            author.id,
            "Jan",
            "Nowak"
        )


def test_update_nonexistent_author(
    service, users
):

    with pytest.raises(NotFoundError):

        service.update_author(
            users["admin"].id,
            999999,
            "Jan",
            "Nowak"
        )


def test_invalid_update_preserves_data(
    service, users, author
):

    with pytest.raises(ValidationError):

        service.update_author(
            users["admin"].id,
            author.id,
            "Jan",
            "123"
        )

    assert author.first_name == "Andrzej"
    assert author.last_name == "Sapkowski"


def test_update_preserves_book_relationships(
    service, users, author, author_books
):

    service.update_author(
        users["admin"].id,
        author.id,
        "Adam",
        "Nowak"
    )

    assert len(author.books) == 2


# DELETE


def test_delete_author(service, users, author):

    author_id = author.id

    result = service.delete_author(
        users["admin"].id,
        author_id
    )

    assert result is True

    assert service.repository.get_by_id(
        author_id
    ) is None


def test_delete_by_librarian(
    service, users, author
):

    author_id = author.id

    service.delete_author(
        users["librarian"].id,
        author_id
    )

    assert service.repository.get_by_id(
        author_id
    ) is None


def test_reader_cannot_delete(
    service, users, author
):

    with pytest.raises(AuthorizationError):

        service.delete_author(
            users["reader"].id,
            author.id
        )


def test_delete_nonexistent_author(
    service, users
):

    with pytest.raises(NotFoundError):

        service.delete_author(
            users["admin"].id,
            999999
        )


@pytest.mark.parametrize(
    "archived",
    [False, True]
)
def test_cannot_delete_associated_author(
    service, users, author, archived
):

    book = Book(
        title="Test Book",
        is_archived=archived
    )

    book.authors.append(author)

    db.session.add(book)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.delete_author(
            users["admin"].id,
            author.id
        )

    assert service.repository.get_by_id(
        author.id
    ) is not None

    assert author in book.authors


# BOOK RELATIONSHIPS


def test_get_active_books(
    service, users, author, author_books
):

    books = service.get_books(
        users["reader"].id,
        author.id
    )

    assert len(books) == 1

    assert books[0].id == (
        author_books["active"].id
    )


def test_get_all_books(
    service, users, author, author_books
):

    books = service.get_books(
        users["admin"].id,
        author.id,
        include_archived=True
    )

    assert len(books) == 2


def test_librarian_archived_access(
    service, users, author, author_books
):

    books = service.get_books(
        users["librarian"].id,
        author.id,
        include_archived=True
    )

    assert len(books) == 2


def test_reader_cannot_access_archived_books(
    service, users, author
):

    with pytest.raises(AuthorizationError):

        service.get_books(
            users["reader"].id,
            author.id,
            include_archived=True
        )


def test_author_without_books(
    service, users, author
):

    assert service.get_books(
        users["reader"].id,
        author.id
    ) == []


def test_count_active_books(
    service, users, author, author_books
):

    assert service.count_books(
        users["reader"].id,
        author.id
    ) == 1


def test_count_all_books(
    service, users, author, author_books
):

    assert service.count_books(
        users["admin"].id,
        author.id,
        include_archived=True
    ) == 2


def test_reader_cannot_count_archived_books(
    service, users, author
):

    with pytest.raises(AuthorizationError):

        service.count_books(
            users["reader"].id,
            author.id,
            include_archived=True
        )


@pytest.mark.parametrize(
    "value",
    ["true", 1, None]
)
def test_invalid_include_archived(
    service, users, author, value
):

    with pytest.raises(ValidationError):

        service.get_books(
            users["admin"].id,
            author.id,
            include_archived=value
        )


def test_multiple_authors_per_book(
    service, users, author
):

    second = service.create_author(
        users["admin"].id,
        "Jan",
        "Nowak"
    )

    book = Book(
        title="Collaborative Book",
        is_archived=False
    )

    book.authors.extend([
        author,
        second
    ])

    db.session.add(book)
    db.session.commit()

    assert len(book.authors) == 2

    assert book in service.get_books(
        users["reader"].id,
        author.id
    )

    assert book in service.get_books(
        users["reader"].id,
        second.id
    )


# AUDIT


def test_creation_audit(author):

    logs = AuditService().get_by_action(
        "AUTHOR_CREATED"
    )

    assert len(logs) == 1


def test_update_audit(service, users, author):

    service.update_author(
        users["admin"].id,
        author.id,
        "Jan",
        "Nowak"
    )

    logs = AuditService().get_by_action(
        "AUTHOR_UPDATED"
    )

    assert len(logs) == 1


def test_delete_audit(service, users, author):

    service.delete_author(
        users["admin"].id,
        author.id
    )

    logs = AuditService().get_by_action(
        "AUTHOR_DELETED"
    )

    assert len(logs) == 1


# TRANSACTIONS


def test_create_transaction_rollback(
    service, users, monkeypatch
):

    def fail_audit(*args, **kwargs):

        raise BusinessRuleError(
            "Simulated audit failure"
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.create_author(
            users["admin"].id,
            "Jan",
            "Nowak"
        )

    assert db.session.query(Author).count() == 0


def test_update_transaction_rollback(
    service, users, author, monkeypatch
):

    def fail_audit(*args, **kwargs):

        raise BusinessRuleError(
            "Simulated audit failure"
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.update_author(
            users["admin"].id,
            author.id,
            "Jan",
            "Nowak"
        )

    assert author.first_name == "Andrzej"
    assert author.last_name == "Sapkowski"


def test_delete_transaction_rollback(
    service, users, author, monkeypatch
):

    author_id = author.id

    def fail_audit(*args, **kwargs):

        raise BusinessRuleError(
            "Simulated audit failure"
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.delete_author(
            users["admin"].id,
            author_id
        )

    assert service.repository.get_by_id(
        author_id
    ) is not None

    assert AuditService().get_by_action(
        "AUTHOR_DELETED"
    ) == []