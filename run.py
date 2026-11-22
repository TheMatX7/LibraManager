import sys

from app import create_app
from app.cli import LibraryCLI
from app.demo import seed_demo_data

app = create_app()

if __name__ == "__main__":
    if "--seed-demo" in sys.argv:
        with app.app_context():
            credentials = seed_demo_data()
        print("Dane demonstracyjne utworzone. Zapisz jednorazowo wygenerowane dane logowania:")
        for role, account in credentials.items():
            print(f"{role}: {account['username']} / {account['password']}")
    elif "--cli" in sys.argv:
        with app.app_context():
            LibraryCLI().run()
    else:
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False
        )
