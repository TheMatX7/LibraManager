import pytest

from app.extensions import db
from app.models import User, Reader
from app.services import AuthService, AuditService

from app.exceptions import (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError
)


PASSWORD = "TestPassword123!"


@pytest.fixture
def service(app):
    return AuthService()


@pytest.fixture
def auth_data(service):

    password_hash = service.hash_password(PASSWORD)

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

    reader_user = User(
        username="reader",
        email="reader@example.com",
        password_hash=password_hash,
        role="READER",
        is_active=True
    )

    other_user = User(
        username="other_reader",
        email="other@example.com",
        password_hash=password_hash,
        role="READER",
        is_active=True
    )

    inactive_user = User(
        username="inactive",
        email="inactive@example.com",
        password_hash=password_hash,
        role="READER",
        is_active=False
    )

    db.session.add_all([
        admin,
        librarian,
        reader_user,
        other_user,
        inactive_user
    ])

    db.session.flush()

    reader = Reader(
        user_id=reader_user.id,
        card_number="CARD001",
        first_name="Jan",
        last_name="Kowalski"
    )

    other_reader = Reader(
        user_id=other_user.id,
        card_number="CARD002",
        first_name="Adam",
        last_name="Nowak"
    )

    db.session.add_all([
        reader,
        other_reader
    ])

    db.session.commit()

    return {
        "admin": admin,
        "librarian": librarian,
        "reader_user": reader_user,
        "other_user": other_user,
        "inactive_user": inactive_user,
        "reader": reader,
        "other_reader": other_reader
    }


# PASSWORD SECURITY


def test_hash_password(service):

    password_hash = service.hash_password(PASSWORD)

    assert password_hash != PASSWORD
    assert password_hash.startswith("scrypt:")
    assert len(password_hash) <= 255


def test_verify_correct_password(service):

    password_hash = service.hash_password(PASSWORD)

    assert service.verify_password(
        password_hash,
        PASSWORD
    )


def test_verify_wrong_password(service):

    password_hash = service.hash_password(PASSWORD)

    assert not service.verify_password(
        password_hash,
        "WrongPassword"
    )


def test_password_unique_salt(service):

    first_hash = service.hash_password(PASSWORD)
    second_hash = service.hash_password(PASSWORD)

    assert first_hash != second_hash


@pytest.mark.parametrize(
    "password",
    ["", "short", None, 123, " " * 12, "A" * 129]
)
def test_invalid_password(service, password):

    with pytest.raises(ValidationError):
        service.hash_password(password)


def test_invalid_password_hash(service):

    assert not service.verify_password(
        "invalid_hash",
        PASSWORD
    )


# AUTHENTICATION


def test_authenticate_admin(service, auth_data):

    user = service.authenticate(
        "admin",
        PASSWORD
    )

    assert user.role == "ADMIN"


def test_authenticate_librarian(service, auth_data):

    user = service.authenticate(
        "librarian",
        PASSWORD
    )

    assert user.role == "LIBRARIAN"


def test_authenticate_reader(service, auth_data):

    user = service.authenticate(
        "reader",
        PASSWORD
    )

    assert user.role == "READER"


def test_authenticate_wrong_password(service, auth_data):

    with pytest.raises(AuthenticationError):
        service.authenticate(
            "admin",
            "WrongPassword"
        )


def test_authenticate_unknown_user(service):

    with pytest.raises(AuthenticationError):
        service.authenticate(
            "unknown_user",
            PASSWORD
        )


def test_authenticate_inactive_user(service, auth_data):

    with pytest.raises(InactiveAccountError):
        service.authenticate(
            "inactive",
            PASSWORD
        )


def test_login_success_audit(service, auth_data):

    service.authenticate(
        "admin",
        PASSWORD
    )

    logs = AuditService().get_by_action(
        "LOGIN_SUCCESS"
    )

    assert len(logs) == 1
    assert logs[0].user_id == auth_data["admin"].id


def test_login_failed_audit(service, auth_data):

    with pytest.raises(AuthenticationError):
        service.authenticate(
            "admin",
            "WrongPassword"
        )

    logs = AuditService().get_by_action(
        "LOGIN_FAILED"
    )

    assert len(logs) == 1


def test_unknown_user_audit(service):

    with pytest.raises(AuthenticationError):
        service.authenticate(
            "unknown",
            PASSWORD
        )

    logs = AuditService().get_by_action(
        "LOGIN_FAILED"
    )

    assert len(logs) == 1
    assert logs[0].user_id is None


@pytest.mark.parametrize(
    "username,password",
    [
        ("", PASSWORD),
        (None, PASSWORD),
        ("admin", ""),
        ("admin", None),
        ("A" * 81, PASSWORD),
        ("admin", "A" * 129)
    ]
)
def test_invalid_login_input(service, username, password):

    with pytest.raises(AuthenticationError):
        service.authenticate(username, password)


# AUTHORIZATION


def test_get_current_user(service, auth_data):

    admin = auth_data["admin"]

    result = service.get_current_user(admin.id)

    assert result.id == admin.id


def test_current_user_not_found(service):

    with pytest.raises(AuthenticationError):
        service.get_current_user(999999)


def test_current_user_inactive(service, auth_data):

    with pytest.raises(InactiveAccountError):
        service.get_current_user(
            auth_data["inactive_user"].id
        )


def test_admin_permission(service, auth_data):

    result = service.require_admin(
        auth_data["admin"].id
    )

    assert result.role == "ADMIN"


def test_librarian_admin_denied(service, auth_data):

    with pytest.raises(AuthorizationError):
        service.require_admin(
            auth_data["librarian"].id
        )


def test_reader_admin_denied(service, auth_data):

    with pytest.raises(AuthorizationError):
        service.require_admin(
            auth_data["reader_user"].id
        )


def test_admin_staff_access(service, auth_data):

    result = service.require_staff(
        auth_data["admin"].id
    )

    assert result.role == "ADMIN"


def test_librarian_staff_access(service, auth_data):

    result = service.require_staff(
        auth_data["librarian"].id
    )

    assert result.role == "LIBRARIAN"


def test_reader_staff_denied(service, auth_data):

    with pytest.raises(AuthorizationError):
        service.require_staff(
            auth_data["reader_user"].id
        )


def test_reader_permission(service, auth_data):

    result = service.require_reader(
        auth_data["reader_user"].id
    )

    assert result.role == "READER"


# ACCESS TO PERSONAL DATA


def test_reader_own_data(service, auth_data):

    result = service.require_reader_access(
        auth_data["reader_user"].id,
        auth_data["reader"].id
    )

    assert result.id == auth_data["reader"].id


def test_reader_other_data_denied(service, auth_data):

    with pytest.raises(AuthorizationError):
        service.require_reader_access(
            auth_data["reader_user"].id,
            auth_data["other_reader"].id
        )


def test_admin_reader_access(service, auth_data):

    result = service.require_reader_access(
        auth_data["admin"].id,
        auth_data["reader"].id
    )

    assert result.id == auth_data["reader"].id


def test_librarian_reader_access(service, auth_data):

    result = service.require_reader_access(
        auth_data["librarian"].id,
        auth_data["reader"].id
    )

    assert result.id == auth_data["reader"].id


def test_nonexistent_reader_access(service, auth_data):

    with pytest.raises(AuthorizationError):
        service.require_reader_access(
            auth_data["admin"].id,
            999999
        )


# LOGOUT


def test_logout(service, auth_data):

    service.logout(
        auth_data["admin"].id
    )

    logs = AuditService().get_by_action(
        "LOGOUT"
    )

    assert len(logs) == 1
    assert logs[0].user_id == auth_data["admin"].id