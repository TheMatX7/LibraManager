import pytest

from app.extensions import db
from app.models import User
from app.services import AuditService
from app.exceptions import (
    ValidationError,
    NotFoundError
)


@pytest.fixture
def service(app):
    return AuditService()


@pytest.fixture
def audit_user(app):

    user = User(
        username="audit_admin",
        email="audit@example.com",
        password_hash="test_hash",
        role="ADMIN",
        is_active=True
    )

    db.session.add(user)
    db.session.commit()

    return user


def test_record_audit(service, audit_user):

    audit = service.record(
        "LOGIN_SUCCESS",
        audit_user.id,
        "User logged in"
    )

    assert audit.id is not None
    assert audit.action == "LOGIN_SUCCESS"
    assert audit.user_id == audit_user.id


def test_system_audit(service):

    audit = service.record(
        "SYSTEM_STARTED",
        description="Application started"
    )

    assert audit.user_id is None
    assert audit.action == "SYSTEM_STARTED"


def test_audit_description(service):

    audit = service.record(
        "TEST_ACTION",
        description="Test description"
    )

    assert audit.description == "Test description"


def test_audit_without_description(service):

    audit = service.record("TEST_ACTION")

    assert audit.description is None


def test_get_audit_by_id(service):

    audit = service.record("TEST_ACTION")

    result = service.get_by_id(audit.id)

    assert result.id == audit.id


def test_get_nonexistent_audit(service):

    with pytest.raises(NotFoundError):
        service.get_by_id(999999)


def test_get_all_audits(service):

    service.record("FIRST_ACTION")
    service.record("SECOND_ACTION")

    assert len(service.get_all()) == 2


def test_get_audits_by_user(service, audit_user):

    service.record("LOGIN_SUCCESS", audit_user.id)
    service.record("LOGOUT", audit_user.id)
    service.record("SYSTEM_STARTED")

    result = service.get_by_user(audit_user.id)

    assert len(result) == 2


def test_get_audits_by_action(service):

    service.record("LOGIN_SUCCESS")
    service.record("LOGIN_SUCCESS")
    service.record("LOGOUT")

    result = service.get_by_action("LOGIN_SUCCESS")

    assert len(result) == 2


def test_get_recent_audits(service):

    service.record("FIRST_ACTION")
    service.record("SECOND_ACTION")
    service.record("THIRD_ACTION")

    result = service.get_recent(limit=2)

    assert len(result) == 2
    assert result[0].action == "THIRD_ACTION"
    assert result[1].action == "SECOND_ACTION"


def test_audit_count(service):

    service.record("FIRST_ACTION")
    service.record("SECOND_ACTION")

    assert service.count() == 2


@pytest.mark.parametrize(
    "action",
    ["", "   ", None, 123, "A" * 101]
)
def test_invalid_action(service, action):

    with pytest.raises(ValidationError):
        service.record(action)


def test_invalid_description(service):

    with pytest.raises(ValidationError):
        service.record(
            "TEST_ACTION",
            description=123
        )


def test_nonexistent_user(service):

    with pytest.raises(NotFoundError):
        service.record(
            "LOGIN_SUCCESS",
            user_id=999999
        )


@pytest.mark.parametrize(
    "limit",
    [0, -1, 1001, "10", 2.5, True]
)
def test_invalid_limit(service, limit):

    with pytest.raises(ValidationError):
        service.get_recent(limit)


def test_audit_rollback(service):

    service.log("TEST_ACTION")

    db.session.flush()
    db.session.rollback()

    assert service.count() == 0


def test_audit_inside_transaction(service):

    with service.transaction():
        service.log("FIRST_ACTION")
        service.log("SECOND_ACTION")

    assert service.count() == 2


def test_audit_failed_transaction(service):

    with pytest.raises(ValidationError):

        with service.transaction():

            service.log("FIRST_ACTION")

            db.session.flush()

            raise ValidationError("Operation failed")

    assert service.count() == 0


def test_action_whitespace(service):

    audit = service.record("  LOGIN_SUCCESS  ")

    assert audit.action == "LOGIN_SUCCESS"


@pytest.mark.parametrize(
    "user_id",
    [0, -1, True, "1"]
)
def test_invalid_user_id(service, user_id):

    with pytest.raises(ValidationError):
        service.record(
            "TEST_ACTION",
            user_id=user_id
        )