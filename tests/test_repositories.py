import pytest

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User
from app.repositories import UserRepository


@pytest.fixture
def repository(app):
    return UserRepository()


@pytest.fixture
def sample_user(repository):
    user = User(
        username="test_reader",
        email="reader@example.com",
        password_hash=generate_password_hash("Test123"),
        role="READER",
        is_active=True
    )

    repository.add(user)
    db.session.commit()

    return user


def test_repository_add(sample_user):
    assert sample_user.id is not None


def test_get_by_id(repository, sample_user):
    user = repository.get_by_id(sample_user.id)
    assert user.username == "test_reader"


def test_get_all(repository, sample_user):
    users = repository.get_all()
    assert len(users) == 1


def test_count(repository, sample_user):
    assert repository.count() == 1


def test_exists(repository, sample_user):
    assert repository.exists(sample_user.id)


def test_get_nonexistent_user(repository):
    assert repository.get_by_id(99999) is None


def test_get_by_username(repository, sample_user):
    user = repository.get_by_username("test_reader")
    assert user.id == sample_user.id


def test_get_by_email(repository, sample_user):
    user = repository.get_by_email("reader@example.com")
    assert user.id == sample_user.id


def test_get_by_role(repository, sample_user):
    users = repository.get_by_role("READER")
    assert len(users) == 1


def test_get_active_users(repository, sample_user):
    assert len(repository.get_active_users()) == 1


def test_get_inactive_users(repository, sample_user):
    sample_user.is_active = False
    db.session.commit()

    assert len(repository.get_inactive_users()) == 1


def test_delete(repository, sample_user):
    user_id = sample_user.id

    repository.delete(sample_user)
    db.session.commit()

    assert repository.get_by_id(user_id) is None