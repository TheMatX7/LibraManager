import pytest

from app.extensions import db
from app.models import User

from app.services import (
    UserService,
    AuthService,
    AuditService
)

from app.exceptions import (
    ValidationError,
    DuplicateError,
    AuthorizationError,
    AuthenticationError,
    BusinessRuleError,
    NotFoundError
)


PASSWORD = "TestPassword123!"
NEW_PASSWORD = "NewPassword123!"


@pytest.fixture
def service(app):
    return UserService()


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

    reader = User(
        username="reader",
        email="reader@example.com",
        password_hash=password_hash,
        role="READER",
        is_active=True
    )

    db.session.add_all([
        admin,
        librarian,
        reader
    ])

    db.session.commit()

    return {
        "admin": admin,
        "librarian": librarian,
        "reader": reader
    }


def test_create_user(service, users):

    user = service.create_user(
        users["admin"].id,
        "new_employee",
        "employee@example.com",
        PASSWORD
    )

    assert user.id is not None
    assert user.role == "LIBRARIAN"
    assert user.is_active is True


def test_create_admin(service, users):

    user = service.create_user(
        users["admin"].id,
        "second_admin",
        "admin2@example.com",
        PASSWORD,
        "ADMIN"
    )

    assert user.role == "ADMIN"


def test_created_user_password_hashed(service, users):

    user = service.create_user(
        users["admin"].id,
        "employee",
        "employee@example.com",
        PASSWORD
    )

    assert user.password_hash != PASSWORD

    assert AuthService().verify_password(
        user.password_hash,
        PASSWORD
    )


def test_duplicate_username(service, users):

    with pytest.raises(DuplicateError):

        service.create_user(
            users["admin"].id,
            "librarian",
            "new@example.com",
            PASSWORD
        )


def test_duplicate_email(service, users):

    with pytest.raises(DuplicateError):

        service.create_user(
            users["admin"].id,
            "employee",
            "LIBRARIAN@EXAMPLE.COM",
            PASSWORD
        )


@pytest.mark.parametrize(
    "username",
    ["", "ab", None, "bad name", "A" * 81]
)
def test_invalid_username(service, users, username):

    with pytest.raises(ValidationError):

        service.create_user(
            users["admin"].id,
            username,
            "new@example.com",
            PASSWORD
        )


@pytest.mark.parametrize(
    "email",
    ["", None, "invalid", "a@", "a b@example.com"]
)
def test_invalid_email(service, users, email):

    with pytest.raises(ValidationError):

        service.create_user(
            users["admin"].id,
            "employee",
            email,
            PASSWORD
        )


def test_invalid_role(service, users):

    with pytest.raises(ValidationError):

        service.create_user(
            users["admin"].id,
            "employee",
            "employee@example.com",
            PASSWORD,
            "SUPERUSER"
        )


def test_librarian_cannot_create_admin(service, users):

    with pytest.raises(AuthorizationError):

        service.create_user(
            users["librarian"].id,
            "employee",
            "employee@example.com",
            PASSWORD,
            "ADMIN"
        )


def test_reader_cannot_create_user(service, users):

    with pytest.raises(AuthorizationError):

        service.create_user(
            users["reader"].id,
            "employee",
            "employee@example.com",
            PASSWORD
        )


def test_reader_creation_requires_reader_service(
    service,
    users
):

    with pytest.raises(BusinessRuleError):

        service.create_user(
            users["admin"].id,
            "new_reader",
            "new@example.com",
            PASSWORD,
            "READER"
        )


def test_get_all_users(service, users):

    result = service.get_all(
        users["admin"].id
    )

    assert len(result) == 3


def test_reader_cannot_list_users(service, users):

    with pytest.raises(AuthorizationError):

        service.get_all(
            users["reader"].id
        )


def test_get_own_account(service, users):

    reader = users["reader"]

    result = service.get_by_id(
        reader.id,
        reader.id
    )

    assert result.id == reader.id


def test_get_other_account_denied(service, users):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            users["reader"].id,
            users["admin"].id
        )


def test_get_nonexistent_user(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["admin"].id,
            999999
        )


def test_get_users_by_role(service, users):

    result = service.get_by_role(
        users["admin"].id,
        "LIBRARIAN"
    )

    assert len(result) == 1


def test_get_active_users(service, users):

    result = service.get_active_users(
        users["admin"].id
    )

    assert len(result) == 3


def test_get_inactive_users(service, users):

    service.deactivate_user(
        users["admin"].id,
        users["reader"].id
    )

    result = service.get_inactive_users(
        users["admin"].id
    )

    assert len(result) == 1


def test_change_password(service, users):

    reader = users["reader"]

    service.change_password(
        reader.id,
        PASSWORD,
        NEW_PASSWORD
    )

    assert AuthService().verify_password(
        reader.password_hash,
        NEW_PASSWORD
    )

    assert not AuthService().verify_password(
        reader.password_hash,
        PASSWORD
    )


def test_change_password_wrong_current(service, users):

    with pytest.raises(AuthenticationError):

        service.change_password(
            users["reader"].id,
            "WrongPassword",
            NEW_PASSWORD
        )


def test_reset_password(service, users):

    reader = users["reader"]

    service.reset_password(
        users["admin"].id,
        reader.id,
        NEW_PASSWORD
    )

    assert AuthService().verify_password(
        reader.password_hash,
        NEW_PASSWORD
    )


def test_reader_cannot_reset_password(service, users):

    with pytest.raises(AuthorizationError):

        service.reset_password(
            users["reader"].id,
            users["admin"].id,
            NEW_PASSWORD
        )


def test_change_role(service, users):

    librarian = users["librarian"]

    service.change_role(
        users["admin"].id,
        librarian.id,
        "ADMIN"
    )

    assert librarian.role == "ADMIN"


def test_protect_last_admin(service, users):

    admin = users["admin"]

    with pytest.raises(BusinessRuleError):

        service.change_role(
            admin.id,
            admin.id,
            "LIBRARIAN"
        )

    assert admin.role == "ADMIN"


def test_reader_role_conversion_denied(service, users):

    with pytest.raises(BusinessRuleError):

        service.change_role(
            users["admin"].id,
            users["reader"].id,
            "LIBRARIAN"
        )


def test_deactivate_user(service, users):

    reader = users["reader"]

    service.deactivate_user(
        users["admin"].id,
        reader.id
    )

    assert reader.is_active is False


def test_activate_user(service, users):

    reader = users["reader"]

    service.deactivate_user(
        users["admin"].id,
        reader.id
    )

    service.activate_user(
        users["admin"].id,
        reader.id
    )

    assert reader.is_active is True


def test_self_deactivation_denied(service, users):

    admin = users["admin"]

    with pytest.raises(BusinessRuleError):

        service.deactivate_user(
            admin.id,
            admin.id
        )

    assert admin.is_active is True


def test_reader_cannot_deactivate_user(service, users):

    with pytest.raises(AuthorizationError):

        service.deactivate_user(
            users["reader"].id,
            users["librarian"].id
        )


def test_user_created_audit(service, users):

    service.create_user(
        users["admin"].id,
        "employee",
        "employee@example.com",
        PASSWORD
    )

    logs = AuditService().get_by_action(
        "USER_CREATED"
    )

    assert len(logs) == 1
    assert logs[0].user_id == users["admin"].id


def test_password_change_audit(service, users):

    service.change_password(
        users["reader"].id,
        PASSWORD,
        NEW_PASSWORD
    )

    logs = AuditService().get_by_action(
        "PASSWORD_CHANGED"
    )

    assert len(logs) == 1
    assert PASSWORD not in logs[0].description
    assert NEW_PASSWORD not in logs[0].description


def test_deactivation_audit(service, users):

    service.deactivate_user(
        users["admin"].id,
        users["reader"].id
    )

    logs = AuditService().get_by_action(
        "USER_DEACTIVATED"
    )

    assert len(logs) == 1


def test_failed_creation_preserves_database(service, users):

    with pytest.raises(ValidationError):

        service.create_user(
            users["admin"].id,
            "employee",
            "employee@example.com",
            "short"
        )

    assert service.repository.count() == 3

    assert AuditService().get_by_action(
        "USER_CREATED"
    ) == []