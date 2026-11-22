import pytest

from app.extensions import db
from app.models import User, Category, Book

from app.services import (
    CategoryService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    DuplicateError,
    AuthorizationError,
    BusinessRuleError,
    NotFoundError
)


@pytest.fixture
def service(app):
    return CategoryService()


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
def category(service, users):

    return service.create_category(
        users["admin"].id,
        "Fantasy",
        "Fantasy literature"
    )


# CREATION


def test_create_category(service, users):

    category = service.create_category(
        users["admin"].id,
        "History",
        "History books"
    )

    assert category.id is not None
    assert category.name == "History"
    assert category.description == "History books"


def test_create_without_description(service, users):

    category = service.create_category(
        users["admin"].id,
        "Science"
    )

    assert category.description is None


def test_create_by_librarian(service, users):

    category = service.create_category(
        users["librarian"].id,
        "Science"
    )

    assert category.id is not None


def test_reader_cannot_create_category(service, users):

    with pytest.raises(AuthorizationError):

        service.create_category(
            users["reader"].id,
            "Science"
        )


@pytest.mark.parametrize(
    "name",
    ["Fantasy", "fantasy", "FANTASY", "  Fantasy  "]
)
def test_duplicate_category(
    service, users, category, name
):

    with pytest.raises(DuplicateError):

        service.create_category(
            users["admin"].id,
            name
        )


def test_unicode_duplicate(service, users):

    service.create_category(
        users["admin"].id,
        "Łączność"
    )

    with pytest.raises(DuplicateError):

        service.create_category(
            users["admin"].id,
            "ŁĄCZNOŚĆ"
        )


def test_unicode_normalization(service, users):

    service.create_category(
        users["admin"].id,
        "Nauka"
    )

    service.create_category(
        users["admin"].id,
        "Życie"
    )

    with pytest.raises(DuplicateError):

        service.create_category(
            users["admin"].id,
            "Z\u0307ycie"
        )


# VALIDATION


@pytest.mark.parametrize(
    "name",
    ["", "   ", None, 123, "A" * 101]
)
def test_invalid_name(service, name):

    with pytest.raises(ValidationError):

        service.validate_name(name)


def test_name_whitespace(service):

    assert service.validate_name(
        "  Fantasy  "
    ) == "Fantasy"


def test_valid_polish_name(service):

    assert service.validate_name(
        "Cyberbezpieczeństwo"
    ) == "Cyberbezpieczeństwo"


@pytest.mark.parametrize(
    "description",
    [123, True, [], "A" * 2001]
)
def test_invalid_description(service, description):

    with pytest.raises(ValidationError):

        service.validate_description(description)


def test_optional_description(service):

    assert service.validate_description(None) is None
    assert service.validate_description("") is None
    assert service.validate_description("   ") is None


def test_description_whitespace(service):

    assert service.validate_description(
        "  Test description  "
    ) == "Test description"


# READ OPERATIONS


def test_get_category_by_id(service, users, category):

    result = service.get_by_id(
        users["reader"].id,
        category.id
    )

    assert result.id == category.id


def test_get_category_by_name(service, users, category):

    result = service.get_by_name(
        users["reader"].id,
        "fAnTaSy"
    )

    assert result.id == category.id


def test_unknown_category_id(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["admin"].id,
            999999
        )


def test_unknown_category_name(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_name(
            users["admin"].id,
            "Nonexistent"
        )


def test_get_all_categories(service, users, category):

    result = service.get_all(
        users["reader"].id
    )

    assert len(result) == 1


def test_sorted_categories(service, users):

    for name in ["Science", "History", "Fantasy"]:

        service.create_category(
            users["admin"].id,
            name
        )

    result = service.get_sorted(
        users["reader"].id
    )

    assert [item.name for item in result] == [
        "Fantasy",
        "History",
        "Science"
    ]


def test_count_categories(service, users, category):

    assert service.count(
        users["reader"].id
    ) == 1


# SEARCH


def test_search_category(service, users, category):

    result = service.search(
        users["reader"].id,
        "fant"
    )

    assert len(result) == 1
    assert result[0].id == category.id


def test_unicode_search(service, users):

    service.create_category(
        users["admin"].id,
        "Łączność"
    )

    result = service.search(
        users["reader"].id,
        "ŁĄCZ"
    )

    assert len(result) == 1


def test_search_no_results(service, users, category):

    result = service.search(
        users["reader"].id,
        "History"
    )

    assert result == []


@pytest.mark.parametrize(
    "query",
    ["", None, "   ", "A" * 101]
)
def test_invalid_search(service, users, query):

    with pytest.raises(ValidationError):

        service.search(
            users["reader"].id,
            query
        )


# UPDATE


def test_update_category(service, users, category):

    service.update_category(
        users["admin"].id,
        category.id,
        "New Fantasy",
        "Updated description"
    )

    assert category.name == "New Fantasy"

    assert category.description == (
        "Updated description"
    )


def test_update_same_name(service, users, category):

    service.update_category(
        users["admin"].id,
        category.id,
        "Fantasy",
        "New description"
    )

    assert category.name == "Fantasy"


def test_update_name_case(service, users, category):

    service.update_category(
        users["admin"].id,
        category.id,
        "FANTASY"
    )

    assert category.name == "FANTASY"


def test_update_duplicate_name(service, users, category):

    second = service.create_category(
        users["admin"].id,
        "History"
    )

    with pytest.raises(DuplicateError):

        service.update_category(
            users["admin"].id,
            second.id,
            "fantasy"
        )

    assert second.name == "History"


def test_update_by_librarian(service, users, category):

    service.update_category(
        users["librarian"].id,
        category.id,
        "Science"
    )

    assert category.name == "Science"


def test_reader_cannot_update(
    service, users, category
):

    with pytest.raises(AuthorizationError):

        service.update_category(
            users["reader"].id,
            category.id,
            "Science"
        )


def test_invalid_update_preserves_data(
    service, users, category
):

    with pytest.raises(ValidationError):

        service.update_category(
            users["admin"].id,
            category.id,
            "New name",
            123
        )

    assert category.name == "Fantasy"


# DELETE


def test_delete_category(service, users, category):

    category_id = category.id

    result = service.delete_category(
        users["admin"].id,
        category_id
    )

    assert result is True
    assert service.repository.get_by_id(category_id) is None


def test_delete_by_librarian(service, users, category):

    category_id = category.id

    service.delete_category(
        users["librarian"].id,
        category_id
    )

    assert service.repository.get_by_id(category_id) is None


def test_reader_cannot_delete(service, users, category):

    with pytest.raises(AuthorizationError):

        service.delete_category(
            users["reader"].id,
            category.id
        )


def test_delete_nonexistent_category(service, users):

    with pytest.raises(NotFoundError):

        service.delete_category(
            users["admin"].id,
            999999
        )


@pytest.mark.parametrize(
    "archived",
    [False, True]
)
def test_cannot_delete_used_category(
    service,
    users,
    category,
    archived
):

    book = Book(
        title="Test Book",
        category_id=category.id,
        is_archived=archived
    )

    db.session.add(book)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.delete_category(
            users["admin"].id,
            category.id
        )

    assert service.repository.get_by_id(
        category.id
    ) is not None

    assert book.category_id == category.id


def test_count_books(service, users, category):

    db.session.add_all([
        Book(
            title="Book One",
            category_id=category.id,
            is_archived=False
        ),
        Book(
            title="Book Two",
            category_id=category.id,
            is_archived=True
        )
    ])

    db.session.commit()

    assert service.count_books(
        users["admin"].id,
        category.id
    ) == 2


def test_count_empty_category(service, users, category):

    assert service.count_books(
        users["librarian"].id,
        category.id
    ) == 0


def test_reader_cannot_count_archived_books(
    service, users, category
):

    with pytest.raises(AuthorizationError):

        service.count_books(
            users["reader"].id,
            category.id
        )


# AUDIT


def test_creation_audit(category):

    logs = AuditService().get_by_action(
        "CATEGORY_CREATED"
    )

    assert len(logs) == 1


def test_update_audit(service, users, category):

    service.update_category(
        users["admin"].id,
        category.id,
        "Science"
    )

    logs = AuditService().get_by_action(
        "CATEGORY_UPDATED"
    )

    assert len(logs) == 1


def test_delete_audit(service, users, category):

    service.delete_category(
        users["admin"].id,
        category.id
    )

    logs = AuditService().get_by_action(
        "CATEGORY_DELETED"
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

        service.create_category(
            users["admin"].id,
            "Science"
        )

    assert db.session.query(Category).count() == 0


def test_delete_transaction_rollback(
    service, users, category, monkeypatch
):

    category_id = category.id

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

        service.delete_category(
            users["admin"].id,
            category_id
        )

    assert service.repository.get_by_id(
        category_id
    ) is not None

    assert AuditService().get_by_action(
        "CATEGORY_DELETED"
    ) == []