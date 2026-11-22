import pytest

from app.extensions import db
from app.models import User, Reader

from app.services import (
    ReaderService,
    AuthService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    DuplicateError,
    AuthorizationError,
    BusinessRuleError,
    NotFoundError
)


PASSWORD = "TestPassword123!"


@pytest.fixture
def service(app):
    return ReaderService()


@pytest.fixture
def users(service):

    password_hash = AuthService().hash_password(
        PASSWORD
    )

    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=password_hash,
        role="ADMIN",
        is_active=True
    )

    librarian = User(
        username="librarian",
        email="librarian@example.com",
        password_hash=password_hash,
        role="LIBRARIAN",
        is_active=True
    )

    db.session.add_all([
        admin,
        librarian
    ])

    db.session.commit()

    return {
        "admin": admin,
        "librarian": librarian
    }


@pytest.fixture
def reader(service, users):

    return service.register_reader(
        actor_id=users["admin"].id,
        username="reader",
        email="reader@example.com",
        password=PASSWORD,
        first_name="Jan",
        last_name="Kowalski",
        phone="123456789"
    )


@pytest.fixture
def other_reader(service, users):

    return service.register_reader(
        actor_id=users["admin"].id,
        username="other_reader",
        email="other@example.com",
        password=PASSWORD,
        first_name="Adam",
        last_name="Nowak"
    )


# REGISTRATION


def test_register_reader(reader):

    assert reader.id is not None
    assert reader.first_name == "Jan"
    assert reader.last_name == "Kowalski"


def test_reader_account_created(reader):

    assert reader.user is not None
    assert reader.user.role == "READER"
    assert reader.user.is_active is True


def test_reader_password_hashed(reader):

    assert reader.user.password_hash != PASSWORD

    assert AuthService().verify_password(
        reader.user.password_hash,
        PASSWORD
    )


def test_reader_card_number(reader):

    assert reader.card_number == (
        f"LIB-{reader.user_id:06d}"
    )


def test_unique_card_numbers(reader, other_reader):

    assert reader.card_number != other_reader.card_number


def test_register_by_librarian(service, users):

    result = service.register_reader(
        users["librarian"].id,
        "new_reader",
        "new@example.com",
        PASSWORD,
        "Anna",
        "Nowak"
    )

    assert result.user.role == "READER"


def test_reader_cannot_register_reader(service, reader):

    with pytest.raises(AuthorizationError):

        service.register_reader(
            reader.user_id,
            "new_reader",
            "new@example.com",
            PASSWORD,
            "Anna",
            "Nowak"
        )


def test_duplicate_reader_username(service, users, reader):

    with pytest.raises(DuplicateError):

        service.register_reader(
            users["admin"].id,
            "reader",
            "new@example.com",
            PASSWORD,
            "Adam",
            "Nowak"
        )


def test_duplicate_reader_email(service, users, reader):

    with pytest.raises(DuplicateError):

        service.register_reader(
            users["admin"].id,
            "new_reader",
            "reader@example.com",
            PASSWORD,
            "Adam",
            "Nowak"
        )


# VALIDATION


@pytest.mark.parametrize(
    "name",
    ["", None, "123", "Jan123", "---", "A" * 81]
)
def test_invalid_name(service, name):

    with pytest.raises(ValidationError):

        service.validate_name(
            name,
            "First name"
        )


def test_polish_name(service):

    assert service.validate_name(
        "Łukasz",
        "First name"
    ) == "Łukasz"


def test_double_surname(service):

    assert service.validate_name(
        "Kowalska-Nowak",
        "Last name"
    ) == "Kowalska-Nowak"


@pytest.mark.parametrize(
    "phone",
    [
        "abc",
        "123",
        "A" * 31,
        123456789,
        "1" * 16
    ]
)
def test_invalid_phone(service, phone):

    with pytest.raises(ValidationError):

        service.validate_phone(phone)


@pytest.mark.parametrize(
    "phone",
    [
        "123456789",
        "+48 123 456 789",
        "(123) 456-789"
    ]
)
def test_valid_phone(service, phone):

    assert service.validate_phone(phone) == phone


def test_optional_phone(service):

    assert service.validate_phone(None) is None
    assert service.validate_phone("") is None


# READER ACCESS


def test_get_reader(service, users, reader):

    result = service.get_by_id(
        users["admin"].id,
        reader.id
    )

    assert result.id == reader.id


def test_get_all_readers(
    service, users, reader, other_reader
):

    result = service.get_all(
        users["admin"].id
    )

    assert len(result) == 2


def test_reader_cannot_list_all(service, reader):

    with pytest.raises(AuthorizationError):

        service.get_all(reader.user_id)


def test_get_reader_by_card(service, users, reader):

    result = service.get_by_card_number(
        users["librarian"].id,
        reader.card_number.lower()
    )

    assert result.id == reader.id


def test_unknown_card(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_card_number(
            users["admin"].id,
            "LIB-999999"
        )


def test_get_own_profile(service, reader):

    result = service.get_own_profile(
        reader.user_id
    )

    assert result.id == reader.id


def test_reader_own_access(service, reader):

    result = service.get_by_id(
        reader.user_id,
        reader.id
    )

    assert result.id == reader.id


def test_reader_other_access_denied(
    service, reader, other_reader
):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            reader.user_id,
            other_reader.id
        )


# SEARCH


def test_search_reader(
    service, users, reader, other_reader
):

    result = service.search(
        users["admin"].id,
        "Kowalski"
    )

    assert len(result) == 1
    assert result[0].id == reader.id


def test_search_by_card(service, users, reader):

    result = service.search(
        users["admin"].id,
        reader.card_number
    )

    assert len(result) == 1


def test_search_no_results(service, users):

    result = service.search(
        users["admin"].id,
        "Nonexistent"
    )

    assert result == []


def test_empty_search(service, users):

    with pytest.raises(ValidationError):

        service.search(
            users["admin"].id,
            ""
        )


def test_reader_cannot_search(service, reader):

    with pytest.raises(AuthorizationError):

        service.search(
            reader.user_id,
            "Kowalski"
        )


# UPDATE


def test_update_reader(service, users, reader):

    service.update_reader(
        users["admin"].id,
        reader.id,
        "Janusz",
        "Kowalski",
        "987654321"
    )

    assert reader.first_name == "Janusz"
    assert reader.phone == "987654321"


def test_update_by_librarian(service, users, reader):

    service.update_reader(
        users["librarian"].id,
        reader.id,
        "Jan",
        "Nowak"
    )

    assert reader.last_name == "Nowak"


def test_reader_cannot_change_name(service, reader):

    with pytest.raises(AuthorizationError):

        service.update_reader(
            reader.user_id,
            reader.id,
            "Adam",
            "Nowak"
        )


def test_update_own_phone(service, reader):

    service.update_own_phone(
        reader.user_id,
        "+48 987654321"
    )

    assert reader.phone == "+48 987654321"


def test_remove_own_phone(service, reader):

    service.update_own_phone(
        reader.user_id,
        None
    )

    assert reader.phone is None


def test_invalid_update_preserves_data(
    service, users, reader
):

    with pytest.raises(ValidationError):

        service.update_reader(
            users["admin"].id,
            reader.id,
            "Adam",
            "123"
        )

    assert reader.first_name == "Jan"
    assert reader.last_name == "Kowalski"


# BUSINESS RULES


def test_require_active_reader(service, reader):

    result = service.require_active_reader(
        reader.id
    )

    assert result.id == reader.id


def test_inactive_reader(service, users, reader):

    service.user_service.deactivate_user(
        users["admin"].id,
        reader.user_id
    )

    with pytest.raises(BusinessRuleError):

        service.require_active_reader(
            reader.id
        )


def test_count_readers(
    service, users, reader, other_reader
):

    assert service.count(
        users["admin"].id
    ) == 2


# AUDIT


def test_registration_audit(reader):

    audit = AuditService()

    assert len(
        audit.get_by_action("USER_CREATED")
    ) == 1

    assert len(
        audit.get_by_action("READER_CREATED")
    ) == 1


def test_reader_update_audit(service, users, reader):

    service.update_reader(
        users["admin"].id,
        reader.id,
        "Janusz",
        "Kowalski"
    )

    logs = AuditService().get_by_action(
        "READER_UPDATED"
    )

    assert len(logs) == 1


def test_phone_update_audit(service, reader):

    service.update_own_phone(
        reader.user_id,
        "987654321"
    )

    logs = AuditService().get_by_action(
        "READER_PHONE_UPDATED"
    )

    assert len(logs) == 1


# TRANSACTIONS


def test_failed_registration(service, users):

    with pytest.raises(ValidationError):

        service.register_reader(
            users["admin"].id,
            "new_reader",
            "new@example.com",
            PASSWORD,
            "",
            "Kowalski"
        )

    assert db.session.query(User).count() == 2
    assert db.session.query(Reader).count() == 0


def test_registration_transaction_rollback(
    service, users, monkeypatch
):

    def fail_registration(*args, **kwargs):

        raise BusinessRuleError(
            "Simulated registration failure"
        )

    monkeypatch.setattr(
        service.repository,
        "add",
        fail_registration
    )

    with pytest.raises(BusinessRuleError):

        service.register_reader(
            users["admin"].id,
            "new_reader",
            "new@example.com",
            PASSWORD,
            "Jan",
            "Kowalski"
        )

    assert db.session.query(User).count() == 2
    assert db.session.query(Reader).count() == 0

    assert AuditService().get_by_action(
        "USER_CREATED"
    ) == []