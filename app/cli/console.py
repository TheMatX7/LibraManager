"""Interactive CLI adapter built exclusively on LibraManager services."""

from decimal import Decimal

from app.exceptions import LibraManagerError
from app.services import (
    AuditService,
    AuthService,
    AuthorService,
    BookService,
    CategoryService,
    CopyService,
    FineService,
    LoanService,
    PaymentService,
    ReaderService,
    ReportService,
    ReservationService,
    SettingService,
    UserService
)


class LibraryCLI:
    """Polish-language terminal UI that delegates every operation to services."""

    def __init__(self, input_fn=input, output_fn=print):
        self.input = input_fn
        self.output = output_fn
        self.user = None
        self.services = {
            "auth": AuthService(), "users": UserService(),
            "readers": ReaderService(), "authors": AuthorService(),
            "categories": CategoryService(), "books": BookService(),
            "copies": CopyService(), "loans": LoanService(),
            "reservations": ReservationService(), "fines": FineService(),
            "payments": PaymentService(), "reports": ReportService(),
            "settings": SettingService(), "audit": AuditService()
        }

    def say(self, message=""):
        self.output(message)

    def ask(self, prompt, required=True):
        value = self.input(f"{prompt}: ").strip()
        if required and not value:
            raise ValueError("To pole jest wymagane.")
        return value

    def ask_id(self, prompt):
        try:
            return int(self.ask(prompt))
        except ValueError as error:
            raise ValueError("Podaj dodatni identyfikator liczbowy.") from error

    def execute(self, action):
        try:
            return action()
        except (LibraManagerError, ValueError) as error:
            self.say(f"Błąd: {error}")
            return None

    def login(self):
        user = self.services["auth"].authenticate(
            self.ask("Login"), self.input("Hasło: ")
        )
        self.user = user
        self.say(f"Zalogowano: {user.username} ({user.role})")

    def _print_books(self, books):
        if not books:
            self.say("Brak książek.")
        for book in books:
            self.say(f"[{book.id}] {book.title} | ISBN: {book.isbn or '—'}")

    def catalog(self):
        phrase = self.ask("Szukaj (Enter = cały katalog)", required=False)
        books = self.services["books"].search(self.user.id, phrase) if phrase else self.services["books"].get_all(self.user.id)
        self._print_books(books)

    def create_book(self):
        title = self.ask("Tytuł")
        isbn = self.ask("ISBN (opcjonalnie)", required=False) or None
        category_id = self.ask("ID kategorii (opcjonalnie)", required=False)
        authors = self.ask("ID autorów po przecinku (opcjonalnie)", required=False)
        author_ids = [int(value.strip()) for value in authors.split(",") if value.strip()]
        book = self.services["books"].create_book(
            self.user.id, title, isbn=isbn,
            category_id=int(category_id) if category_id else None,
            author_ids=author_ids
        )
        self.say(f"Dodano książkę #{book.id}.")

    def register_reader(self):
        reader = self.services["readers"].register_reader(
            self.user.id, self.ask("Login"), self.ask("E-mail"),
            self.input("Hasło (min. 12 znaków): "), self.ask("Imię"),
            self.ask("Nazwisko"), self.ask("Telefon", required=False) or None
        )
        self.say(f"Utworzono czytelnika {reader.card_number}.")

    def loan_book(self):
        loan = self.services["loans"].borrow_book(
            self.user.id, self.ask_id("ID czytelnika"), self.ask_id("ID egzemplarza")
        )
        self.say(f"Wypożyczenie #{loan.id}; termin zwrotu: {loan.due_date}.")

    def return_book(self):
        loan = self.services["loans"].return_book(self.user.id, self.ask_id("ID wypożyczenia"))
        self.say(f"Przyjęto zwrot wypożyczenia #{loan.id}.")

    def make_reservation(self):
        if self.user.role == "READER":
            reservation = self.services["reservations"].create_own_reservation(self.user.id, self.ask_id("ID książki"))
        else:
            reservation = self.services["reservations"].create_reservation(
                self.user.id, self.ask_id("ID czytelnika"), self.ask_id("ID książki")
            )
        self.say(f"Utworzono rezerwację #{reservation.id}: {reservation.status}.")

    def cancel_reservation(self):
        reservation = self.services["reservations"].cancel_reservation(self.user.id, self.ask_id("ID rezerwacji"))
        self.say(f"Anulowano rezerwację #{reservation.id}.")

    def register_payment(self):
        payment = self.services["payments"].register_payment(
            self.user.id, self.ask_id("ID kary"), self.ask("Kwota"), self.ask("Metoda CASH/CARD")
        )
        self.say(f"Zarejestrowano płatność #{payment.id}: {payment.amount} PLN.")

    def own_overview(self):
        loans = self.services["loans"].get_own_active_loans(self.user.id)
        fines = self.services["fines"].get_own_summary(self.user.id)
        reservations = self.services["reservations"].get_own_active_reservations(self.user.id)
        self.say(f"Aktywne wypożyczenia: {len(loans)} | rezerwacje: {len(reservations)} | zadłużenie: {fines['total_unpaid']} PLN")

    def staff_overview(self):
        overview = self.services["reports"].get_library_overview(self.user.id)
        self.say(f"Książki: {overview['books']}; dostępne egzemplarze: {overview['available_copies']}; aktywne wypożyczenia: {overview['active_loans']}; przeterminowane: {overview['overdue_loans']}.")

    def reports(self):
        report = self.services["reports"].get_financial_statistics(self.user.id)
        self.say(f"Zadłużenie: {report['outstanding_amount']} PLN; zarejestrowane płatności: {report['registered_payment_amount']} PLN.")

    def change_phone(self):
        reader = self.services["readers"].update_own_phone(self.user.id, self.ask("Nowy telefon", required=False) or None)
        self.say(f"Zaktualizowano telefon czytelnika {reader.card_number}.")

    def change_password(self):
        self.services["users"].change_password(self.user.id, self.input("Obecne hasło: "), self.input("Nowe hasło: "))
        self.say("Hasło zostało zmienione.")

    def admin_settings(self):
        settings = self.services["settings"].get_all()
        for key, value in settings.items():
            self.say(f"{key} = {value}")
        key = self.ask("Klucz ustawienia")
        value = self.ask("Nowa wartość")
        self.services["settings"].update(key, value)
        self.say("Zapisano ustawienie.")

    def menu(self):
        if self.user.role == "READER":
            return {
                "1": ("Katalog", self.catalog), "2": ("Moje podsumowanie", self.own_overview),
                "3": ("Utwórz rezerwację", self.make_reservation), "4": ("Anuluj rezerwację", self.cancel_reservation),
                "5": ("Zmień telefon", self.change_phone), "6": ("Zmień hasło", self.change_password)
            }
        options = {
            "1": ("Katalog", self.catalog), "2": ("Dodaj książkę", self.create_book),
            "3": ("Zarejestruj czytelnika", self.register_reader), "4": ("Wypożycz egzemplarz", self.loan_book),
            "5": ("Przyjmij zwrot", self.return_book), "6": ("Utwórz rezerwację", self.make_reservation),
            "7": ("Anuluj rezerwację", self.cancel_reservation), "8": ("Zarejestruj płatność", self.register_payment),
            "9": ("Podsumowanie biblioteki", self.staff_overview), "10": ("Raport finansowy", self.reports)
        }
        if self.user.role == "ADMIN":
            options["11"] = ("Ustawienia", self.admin_settings)
        return options

    def run(self):
        self.services["settings"].initialize_defaults()
        self.say("\n=== LibraManager CLI ===")
        while self.user is None:
            choice = self.input("[1] Logowanie  [0] Zakończ: ").strip()
            if choice == "0":
                return
            if choice == "1":
                self.execute(self.login)
        while self.user is not None:
            options = self.menu()
            self.say("\n" + " | ".join(f"[{key}] {label}" for key, (label, _) in options.items()))
            choice = self.input("[L] Wyloguj  [0] Zakończ: ").strip().upper()
            if choice == "0":
                return
            if choice == "L":
                self.execute(lambda: self.services["auth"].logout(self.user.id))
                self.user = None
                continue
            item = options.get(choice)
            if item is None:
                self.say("Nieznana opcja.")
            else:
                self.execute(item[1])
