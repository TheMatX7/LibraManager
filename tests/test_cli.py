from app.cli import LibraryCLI
from app.extensions import db
from app.models import User
from app.services import AuthService


def test_cli_exits_without_authentication(app):
    answers = iter(["0"])
    output = []

    LibraryCLI(
        input_fn=lambda prompt: next(answers),
        output_fn=output.append
    ).run()

    assert any("LibraManager CLI" in line for line in output)


def test_cli_logs_in_and_uses_catalog_service(app):
    password = "CliInterfacePassword123!"
    user = User(
        username="cli_staff",
        email="cli-staff@example.test",
        password_hash=AuthService().hash_password(password),
        role="LIBRARIAN",
        is_active=True
    )
    db.session.add(user)
    db.session.commit()

    answers = iter([
        "1", "cli_staff", password, "1", "", "0"
    ])
    output = []

    LibraryCLI(
        input_fn=lambda prompt: next(answers),
        output_fn=output.append
    ).run()

    assert any("Zalogowano: cli_staff" in line for line in output)
    assert any("Brak książek" in line for line in output)
