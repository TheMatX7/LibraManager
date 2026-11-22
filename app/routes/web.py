"""Server-rendered LibraManager web interface.

Routes deliberately contain presentation/input adaptation only.  Each read or
write is delegated to a service, so CLI and HTTP share exactly the same rules.
"""

from collections import defaultdict, deque
from functools import wraps
from threading import Lock
from time import monotonic

from flask import (
    Blueprint,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for
)

from app.exceptions import LibraManagerError, ValidationError
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


web = Blueprint("web", __name__)


class LoginAttemptGuard:
    """Small in-process rate guard for password guessing.

    It is intentionally fail-closed for a short period.  Deployments with
    multiple workers should replace this with shared rate limiting at the
    reverse proxy or cache layer.
    """

    def __init__(self, limit=5, window_seconds=300):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts = defaultdict(deque)
        self._lock = Lock()

    def _key(self, request):
        # Do not trust a client-controlled X-Forwarded-For header here.
        # A reverse proxy may replace REMOTE_ADDR only after it is configured
        # as a trusted proxy in the deployment environment.
        return request.remote_addr or ""

    def is_blocked(self, request):
        key = self._key(request)
        current = monotonic()
        with self._lock:
            attempts = self._attempts[key]
            while attempts and current - attempts[0] >= self.window_seconds:
                attempts.popleft()
            return len(attempts) >= self.limit

    def record_failure(self, request):
        with self._lock:
            self._attempts[self._key(request)].append(monotonic())

    def clear(self, request):
        with self._lock:
            self._attempts.pop(self._key(request), None)


login_guard = LoginAttemptGuard()


def services():
    """Create service facades for the current request without ORM access."""

    return {
        "auth": AuthService(),
        "users": UserService(),
        "readers": ReaderService(),
        "categories": CategoryService(),
        "authors": AuthorService(),
        "books": BookService(),
        "copies": CopyService(),
        "loans": LoanService(),
        "reservations": ReservationService(),
        "fines": FineService(),
        "payments": PaymentService(),
        "reports": ReportService(),
        "settings": SettingService(),
        "audit": AuditService()
    }


def actor_id():
    return g.user.id


def parse_int(name, required=True):
    value = request.form.get(name, "").strip()
    if not value and not required:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValidationError(f"Pole {name} musi być liczbą całkowitą.") from error


def parse_year(name):
    return parse_int(name, required=False)


def parse_ids(name):
    values = request.form.getlist(name)
    try:
        return [int(value) for value in values if value.strip()]
    except ValueError as error:
        raise ValidationError("Nieprawidłowy identyfikator w formularzu.") from error


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "user", None) is None:
            flash("Zaloguj się, aby kontynuować.", "warning")
            return redirect(url_for("web.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user.role not in roles:
                flash("Nie masz uprawnień do tej operacji.", "danger")
                return redirect(url_for("web.dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def execute(operation, success_message, destination):
    """Run a service action and keep domain errors out of presentation code."""

    try:
        operation()
    except LibraManagerError as error:
        flash(str(error), "danger")
    else:
        flash(success_message, "success")
    return redirect(destination)


def rows_from(items, columns):
    rows = []
    for item in items:
        row = {"_id": getattr(item, "id", None)}
        for key, _ in columns:
            value = item
            for part in key.split("."):
                value = getattr(value, part, None)
                if value is None:
                    break
            row[key] = value
        rows.append(row)
    return rows


def paginated(rows):
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 12
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(page, total_pages)
    return rows[(page - 1) * per_page:page * per_page], page, total_pages


@web.before_request
def load_current_user():
    g.user = None
    raw_id = session.get("user_id")
    if raw_id is None:
        return
    try:
        g.user = AuthService().get_current_user(raw_id)
    except LibraManagerError:
        session.clear()


@web.context_processor
def inject_layout_context():
    return {"current_user": getattr(g, "user", None)}


@web.route("/")
def index():
    return redirect(url_for("web.dashboard" if g.user else "web.login"))


@web.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("web.dashboard"))

    if request.method == "POST":
        if login_guard.is_blocked(request):
            flash("Zbyt wiele prób logowania. Spróbuj ponownie za kilka minut.", "danger")
            return render_template("login.html"), 429
        try:
            user = AuthService().authenticate(
                request.form.get("username", ""),
                request.form.get("password", "")
            )
        except LibraManagerError:
            login_guard.record_failure(request)
            flash("Nieprawidłowy login lub hasło.", "danger")
        else:
            login_guard.clear(request)
            # Session fixation protection requires replacing the session at
            # login. Preserve only Flask-WTF's server-side CSRF secret so the
            # next authenticated form remains valid.
            csrf_secret = session.get("csrf_token")
            session.clear()
            if csrf_secret:
                session["csrf_token"] = csrf_secret
            session["user_id"] = user.id
            session.permanent = True
            flash(f"Witaj, {user.username}.", "success")
            return redirect(url_for("web.dashboard"))
    return render_template("login.html")


@web.post("/logout")
@login_required
def logout():
    try:
        services()["auth"].logout(actor_id())
    except LibraManagerError:
        pass
    session.clear()
    flash("Wylogowano pomyślnie.", "success")
    return redirect(url_for("web.login"))


@web.route("/dashboard")
@login_required
def dashboard():
    api = services()
    if g.user.role == "ADMIN":
        data = api["reports"].get_admin_dashboard(actor_id())
        return render_template("dashboard.html", dashboard=data, reader=False)
    if g.user.role == "LIBRARIAN":
        return render_template(
            "dashboard.html",
            dashboard={
                "library": api["reports"].get_library_overview(actor_id()),
                "financial": api["reports"].get_financial_statistics(actor_id())
            },
            reader=False
        )
    return render_template(
        "dashboard.html",
        reader=True,
        dashboard={
            "loans": api["loans"].get_own_active_loans(actor_id()),
            "fines": api["fines"].get_own_summary(actor_id()),
            "reservations": api["reservations"].get_own_active_reservations(actor_id())
        }
    )


@web.route("/catalog")
@login_required
def catalog():
    api = services()
    query = request.args.get("q", "").strip()
    include_archived = (
        g.user.role != "READER"
        and request.args.get("archived") == "1"
    )
    books = api["books"].search(actor_id(), query, include_archived) if query else api["books"].get_all(actor_id(), include_archived)
    columns = [("title", "Tytuł"), ("isbn", "ISBN"), ("category.name", "Kategoria"), ("publisher", "Wydawca"), ("is_archived", "Archiwum")]
    rows, page, pages = paginated(rows_from(books, columns))
    return render_template("collection.html", title="Katalog książek", columns=columns, rows=rows, page=page, pages=pages, query=query, create_url=url_for("web.book_new") if g.user.role != "READER" else None, detail_endpoint="web.book_detail")


@web.route("/books/<int:book_id>")
@login_required
def book_detail(book_id):
    api = services()
    book = api["books"].get_by_id(actor_id(), book_id)
    return render_template("book_detail.html", book=book, availability=api["books"].get_availability(actor_id(), book_id))


@web.route("/books/new", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def book_new():
    api = services()
    if request.method == "POST":
        return execute(
            lambda: api["books"].create_book(
                actor_id(), request.form.get("title"), request.form.get("isbn") or None,
                request.form.get("description") or None, request.form.get("publisher") or None,
                parse_year("publication_year"), parse_int("category_id", required=False), parse_ids("author_ids")
            ), "Dodano książkę.", url_for("web.catalog")
        )
    return render_template("book_form.html", categories=api["categories"].get_sorted(actor_id()), authors=api["authors"].get_sorted(actor_id()), book=None)


@web.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def book_edit(book_id):
    api = services()
    book = api["books"].get_by_id(actor_id(), book_id, include_archived=True)
    if request.method == "POST":
        return execute(
            lambda: api["books"].update_book(
                actor_id(), book_id, request.form.get("title"), request.form.get("isbn") or None,
                request.form.get("description") or None, request.form.get("publisher") or None,
                parse_year("publication_year"), parse_int("category_id", required=False), parse_ids("author_ids")
            ), "Zaktualizowano książkę.", url_for("web.book_detail", book_id=book_id)
        )
    return render_template("book_form.html", categories=api["categories"].get_sorted(actor_id()), authors=api["authors"].get_sorted(actor_id()), book=book)


@web.post("/books/<int:book_id>/archive")
@role_required("ADMIN", "LIBRARIAN")
def book_archive(book_id):
    return execute(lambda: services()["books"].archive_book(actor_id(), book_id), "Zarchiwizowano książkę.", url_for("web.catalog"))


@web.post("/books/<int:book_id>/restore")
@role_required("ADMIN", "LIBRARIAN")
def book_restore(book_id):
    return execute(lambda: services()["books"].restore_book(actor_id(), book_id), "Przywrócono książkę.", url_for("web.catalog", archived=1))


@web.route("/authors", methods=["GET", "POST"])
@login_required
def authors():
    api = services()
    if request.method == "POST":
        if g.user.role == "READER":
            flash("Nie masz uprawnień do dodawania autorów.", "danger")
        else:
            return execute(lambda: api["authors"].create_author(actor_id(), request.form.get("first_name"), request.form.get("last_name")), "Dodano autora.", url_for("web.authors"))
    query = request.args.get("q", "").strip()
    items = api["authors"].search(actor_id(), query) if query else api["authors"].get_sorted(actor_id())
    columns = [("first_name", "Imię"), ("last_name", "Nazwisko")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Autorzy", columns=columns, rows=rows, page=page, pages=pages, query=query, inline_form="author" if g.user.role != "READER" else None)


@web.route("/authors/<int:author_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def author_edit(author_id):
    api = services()
    author = api["authors"].get_by_id(actor_id(), author_id)
    if request.method == "POST":
        return execute(lambda: api["authors"].update_author(actor_id(), author_id, request.form.get("first_name"), request.form.get("last_name")), "Zaktualizowano autora.", url_for("web.authors"))
    return render_template("entity_form.html", kind="author", item=author)


@web.post("/authors/<int:author_id>/delete")
@role_required("ADMIN", "LIBRARIAN")
def author_delete(author_id):
    return execute(lambda: services()["authors"].delete_author(actor_id(), author_id), "Usunięto autora.", url_for("web.authors"))


@web.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    api = services()
    if request.method == "POST":
        if g.user.role == "READER":
            flash("Nie masz uprawnień do dodawania kategorii.", "danger")
        else:
            return execute(lambda: api["categories"].create_category(actor_id(), request.form.get("name"), request.form.get("description") or None), "Dodano kategorię.", url_for("web.categories"))
    query = request.args.get("q", "").strip()
    items = api["categories"].search(actor_id(), query) if query else api["categories"].get_sorted(actor_id())
    columns = [("name", "Nazwa"), ("description", "Opis")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Kategorie", columns=columns, rows=rows, page=page, pages=pages, query=query, inline_form="category" if g.user.role != "READER" else None)


@web.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def category_edit(category_id):
    api = services()
    category = api["categories"].get_by_id(actor_id(), category_id)
    if request.method == "POST":
        return execute(lambda: api["categories"].update_category(actor_id(), category_id, request.form.get("name"), request.form.get("description") or None), "Zaktualizowano kategorię.", url_for("web.categories"))
    return render_template("entity_form.html", kind="category", item=category)


@web.post("/categories/<int:category_id>/delete")
@role_required("ADMIN", "LIBRARIAN")
def category_delete(category_id):
    return execute(lambda: services()["categories"].delete_category(actor_id(), category_id), "Usunięto kategorię.", url_for("web.categories"))


@web.route("/copies", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def copies():
    api = services()
    if request.method == "POST":
        return execute(lambda: api["copies"].create_copy(actor_id(), parse_int("book_id"), request.form.get("inventory_number")), "Dodano egzemplarz.", url_for("web.copies"))
    query = request.args.get("q", "").strip()
    items = api["copies"].search(actor_id(), query) if query else api["copies"].get_all(actor_id())
    columns = [("inventory_number", "Numer inwentarzowy"), ("book.title", "Książka"), ("status", "Status")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Egzemplarze", columns=columns, rows=rows, page=page, pages=pages, query=query, inline_form="copy", books=api["books"].get_all(actor_id()))


@web.route("/copies/<int:copy_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def copy_edit(copy_id):
    api = services()
    copy = api["copies"].get_by_id(actor_id(), copy_id)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "status":
            return execute(lambda: api["copies"].change_status(actor_id(), copy_id, request.form.get("status")), "Zmieniono status egzemplarza.", url_for("web.copies"))
        return execute(lambda: api["copies"].update_copy(actor_id(), copy_id, request.form.get("inventory_number")), "Zaktualizowano egzemplarz.", url_for("web.copies"))
    return render_template("entity_form.html", kind="copy", item=copy, statuses=CopyService.MANUAL_STATUSES)


@web.post("/copies/<int:copy_id>/delete")
@role_required("ADMIN", "LIBRARIAN")
def copy_delete(copy_id):
    return execute(lambda: services()["copies"].delete_copy(actor_id(), copy_id), "Usunięto egzemplarz.", url_for("web.copies"))


@web.route("/readers", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def readers():
    api = services()
    if request.method == "POST":
        return execute(lambda: api["readers"].register_reader(actor_id(), request.form.get("username"), request.form.get("email"), request.form.get("password"), request.form.get("first_name"), request.form.get("last_name"), request.form.get("phone") or None), "Zarejestrowano czytelnika.", url_for("web.readers"))
    query = request.args.get("q", "").strip()
    items = api["readers"].search(actor_id(), query) if query else api["readers"].get_all(actor_id())
    columns = [("card_number", "Karta"), ("first_name", "Imię"), ("last_name", "Nazwisko"), ("phone", "Telefon")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Czytelnicy", columns=columns, rows=rows, page=page, pages=pages, query=query, inline_form="reader")


@web.route("/readers/<int:reader_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LIBRARIAN")
def reader_edit(reader_id):
    api = services()
    reader = api["readers"].get_by_id(actor_id(), reader_id)
    if request.method == "POST":
        return execute(lambda: api["readers"].update_reader(actor_id(), reader_id, request.form.get("first_name"), request.form.get("last_name"), request.form.get("phone") or None), "Zaktualizowano czytelnika.", url_for("web.readers"))
    return render_template("entity_form.html", kind="reader", item=reader)


@web.route("/users", methods=["GET", "POST"])
@role_required("ADMIN")
def users():
    api = services()
    if request.method == "POST":
        return execute(lambda: api["users"].create_user(actor_id(), request.form.get("username"), request.form.get("email"), request.form.get("password"), request.form.get("role")), "Utworzono konto pracownika.", url_for("web.users"))
    role = request.args.get("role", "").strip().upper()
    items = api["users"].get_by_role(actor_id(), role) if role else api["users"].get_all(actor_id())
    columns = [("username", "Login"), ("email", "E-mail"), ("role", "Rola"), ("is_active", "Aktywne")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Użytkownicy", columns=columns, rows=rows, page=page, pages=pages, inline_form="user", role=role)


@web.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def user_edit(user_id):
    api = services()
    user = api["users"].get_by_id(actor_id(), user_id)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            return execute(lambda: api["users"].reset_password(actor_id(), user_id, request.form.get("new_password")), "Zresetowano hasło użytkownika.", url_for("web.users"))
        return execute(lambda: api["users"].change_role(actor_id(), user_id, request.form.get("role")), "Zmieniono rolę użytkownika.", url_for("web.users"))
    return render_template("entity_form.html", kind="user", item=user)


@web.post("/users/<int:user_id>/toggle")
@role_required("ADMIN")
def user_toggle(user_id):
    api = services()
    user = api["users"].get_by_id(actor_id(), user_id)
    method = api["users"].deactivate_user if user.is_active else api["users"].activate_user
    return execute(lambda: method(actor_id(), user_id), "Zmieniono status konta.", url_for("web.users"))


@web.route("/loans", methods=["GET", "POST"])
@login_required
def loans():
    api = services()
    if request.method == "POST":
        if g.user.role == "READER":
            flash("Wypożyczenia rejestruje pracownik biblioteki.", "danger")
        else:
            return execute(lambda: api["loans"].borrow_book(actor_id(), parse_int("reader_id"), parse_int("copy_id")), "Zarejestrowano wypożyczenie.", url_for("web.loans"))
    status = request.args.get("status", "").strip().upper()
    if g.user.role == "READER":
        items = api["loans"].get_own_loans(actor_id())
        if status:
            items = [loan for loan in items if loan.status == status]
    else:
        items = api["loans"].get_by_status(actor_id(), status) if status else api["loans"].get_all(actor_id())
    columns = [("id", "ID"), ("copy.inventory_number", "Egzemplarz"), ("reader.card_number", "Czytelnik"), ("due_date", "Termin"), ("status", "Status")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Wypożyczenia", columns=columns, rows=rows, page=page, pages=pages, status=status, status_options=LoanService.VALID_STATUSES, inline_form="loan" if g.user.role != "READER" else None, readers=api["readers"].get_all(actor_id()) if g.user.role != "READER" else [], copies=api["copies"].get_by_status(actor_id(), "AVAILABLE") if g.user.role != "READER" else [])


@web.post("/loans/<int:loan_id>/return")
@role_required("ADMIN", "LIBRARIAN")
def loan_return(loan_id):
    return execute(lambda: services()["loans"].return_book(actor_id(), loan_id), "Przyjęto zwrot.", url_for("web.loans"))


@web.route("/reservations", methods=["GET", "POST"])
@login_required
def reservations():
    api = services()
    if request.method == "POST":
        if g.user.role == "READER":
            operation = lambda: api["reservations"].create_own_reservation(actor_id(), parse_int("book_id"))
        else:
            operation = lambda: api["reservations"].create_reservation(actor_id(), parse_int("reader_id"), parse_int("book_id"))
        return execute(operation, "Utworzono rezerwację.", url_for("web.reservations"))
    status = request.args.get("status", "").strip().upper()
    if g.user.role == "READER":
        items = api["reservations"].get_own_reservations(actor_id())
        if status:
            items = [reservation for reservation in items if reservation.status == status]
    else:
        items = api["reservations"].get_by_status(actor_id(), status) if status else api["reservations"].get_all(actor_id())
    columns = [("id", "ID"), ("book.title", "Książka"), ("reader.card_number", "Czytelnik"), ("status", "Status"), ("expires_at", "Odbiór do")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Rezerwacje", columns=columns, rows=rows, page=page, pages=pages, status=status, status_options=ReservationService.VALID_STATUSES, inline_form="reservation", books=api["books"].get_all(actor_id()), readers=api["readers"].get_all(actor_id()) if g.user.role != "READER" else [])


@web.post("/reservations/<int:reservation_id>/cancel")
@login_required
def reservation_cancel(reservation_id):
    return execute(lambda: services()["reservations"].cancel_reservation(actor_id(), reservation_id), "Anulowano rezerwację.", url_for("web.reservations"))


@web.route("/fines")
@login_required
def fines():
    api = services()
    status = request.args.get("status", "").strip().upper()
    if g.user.role == "READER":
        items = api["fines"].get_own_fines(actor_id())
        if status:
            items = [fine for fine in items if fine.status == status]
    else:
        items = api["fines"].get_by_status(actor_id(), status) if status else api["fines"].get_all(actor_id())
    columns = [("id", "ID"), ("loan.reader.card_number", "Czytelnik"), ("amount", "Kwota"), ("paid_amount", "Opłacono"), ("status", "Status")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Kary finansowe", columns=columns, rows=rows, page=page, pages=pages, status=status, status_options=FineService.VALID_STATUSES)


@web.route("/payments", methods=["GET", "POST"])
@login_required
def payments():
    api = services()
    if request.method == "POST":
        if g.user.role == "READER":
            flash("Czytelnik nie może rejestrować płatności.", "danger")
        else:
            return execute(lambda: api["payments"].register_payment(actor_id(), parse_int("fine_id"), request.form.get("amount"), request.form.get("method")), "Zarejestrowano płatność.", url_for("web.payments"))
    method = request.args.get("method", "").strip().upper()
    if g.user.role == "READER":
        items = api["payments"].get_own_payments_by_method(actor_id(), method) if method else api["payments"].get_own_payments(actor_id())
    else:
        items = api["payments"].get_by_method(actor_id(), method) if method else api["payments"].get_all(actor_id())
    columns = [("id", "ID"), ("fine_id", "Kara"), ("amount", "Kwota"), ("method", "Metoda"), ("paid_at", "Data")]
    rows, page, pages = paginated(rows_from(items, columns))
    fines = api["fines"].get_unpaid_fines(actor_id()) if g.user.role != "READER" else []
    return render_template("collection.html", title="Płatności", columns=columns, rows=rows, page=page, pages=pages, method=method, inline_form="payment" if g.user.role != "READER" else None, fines=fines)


@web.route("/reports")
@role_required("ADMIN", "LIBRARIAN")
def reports():
    api = services()
    top_books = api["reports"].get_most_borrowed_books(actor_id())
    return render_template(
        "reports.html",
        overview=api["reports"].get_library_overview(actor_id()),
        financial=api["reports"].get_financial_statistics(actor_id()),
        loans=api["reports"].get_loan_statistics(actor_id()),
        top_books=top_books,
        top_book_max=max((book["loan_count"] for book in top_books), default=1)
    )


@web.route("/reports/<report_name>.csv")
@role_required("ADMIN", "LIBRARIAN")
def report_export(report_name):
    content = services()["reports"].export_csv(actor_id(), report_name)
    return Response(content, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="libra-{report_name}.csv"'})


@web.route("/settings", methods=["GET", "POST"])
@role_required("ADMIN")
def settings():
    api = services()
    if request.method == "POST":
        return execute(lambda: api["settings"].update(request.form.get("key"), request.form.get("value")), "Zaktualizowano ustawienie.", url_for("web.settings"))
    return render_template("settings.html", settings=api["settings"].get_all(), descriptions=api["settings"].DEFAULT_SETTINGS)


@web.route("/audit")
@role_required("ADMIN")
def audit():
    items = services()["audit"].get_recent(100)
    columns = [("created_at", "Data"), ("action", "Operacja"), ("user_id", "Użytkownik"), ("description", "Opis")]
    rows, page, pages = paginated(rows_from(items, columns))
    return render_template("collection.html", title="Dziennik audytu", columns=columns, rows=rows, page=page, pages=pages)


@web.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    api = services()
    if request.method == "POST":
        if request.form.get("action") == "password":
            return execute(lambda: api["users"].change_password(actor_id(), request.form.get("current_password"), request.form.get("new_password")), "Zmieniono hasło.", url_for("web.profile"))
        if g.user.role == "READER":
            return execute(lambda: api["readers"].update_own_phone(actor_id(), request.form.get("phone")), "Zaktualizowano profil.", url_for("web.profile"))
    reader = api["readers"].get_own_profile(actor_id()) if g.user.role == "READER" else None
    return render_template("profile.html", reader=reader)
