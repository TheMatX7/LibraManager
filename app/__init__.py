import os
import secrets

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from app.config import Config
from app.extensions import db, csrf
from app.exceptions import LibraManagerError


def create_app(test_config=None):
    app = Flask(__name__)

    app.config.from_object(Config)

    if test_config is not None:
        app.config.update(test_config)

    # A secret key is never hard-coded.  A temporary value keeps local
    # development usable when .env has not yet been created, while production
    # requires an explicit environment value.
    if not app.config.get("SECRET_KEY"):
        if os.getenv("FLASK_ENV") == "production":
            raise RuntimeError("SECRET_KEY must be configured in production.")
        app.config["SECRET_KEY"] = secrets.token_urlsafe(48)

    db.init_app(app)
    csrf.init_app(app)

    from app.models import models

    from app.routes.web import web
    app.register_blueprint(web)

    @app.route("/health")
    def health():
        return {"status": "healthy"}

    @app.route("/favicon.ico")
    def favicon():
        # Avoid a noisy 404 in browsers without introducing a binary asset.
        return "", 204

    @app.errorhandler(LibraManagerError)
    def handle_domain_error(error):
        if app.config.get("TESTING"):
            raise error
        if request.accept_mimetypes.accept_html:
            return render_template(
                "error.html",
                code=400,
                title="Nie można wykonać operacji",
                message=str(error),
            ), 400
        return jsonify({"error": "Wystąpił błąd operacji."}), 400

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if app.config.get("TESTING"):
            return error
        if request.accept_mimetypes.accept_html:
            titles = {
                400: "Nieprawidłowe żądanie",
                403: "Brak dostępu",
                404: "Nie znaleziono strony",
                405: "Niedozwolona metoda",
                429: "Zbyt wiele żądań",
            }
            return render_template(
                "error.html",
                code=error.code,
                title=titles.get(error.code, error.name),
                message=error.description,
            ), error.code
        return jsonify({"error": error.name}), error.code

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    with app.app_context():
        db.create_all()

    return app
