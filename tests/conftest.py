import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app():

    application = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "testing-secret-key"
    })

    with application.app_context():

        try:

            yield application

        finally:

            try:

                db.session.remove()

                db.drop_all()

            finally:

                db.session.remove()

                db.engine.dispose()


@pytest.fixture
def client(app):

    return app.test_client()