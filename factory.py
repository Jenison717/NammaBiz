from pathlib import Path

from flask import Flask, Response, abort, redirect, request
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlalchemy import inspect

from config import Config, ROOT, validate_config
from extensions import csrf, db, login_manager, migrate
from models import User
from utils.validators import valid_email, valid_password


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def _database_uri(db_path=None):
    if db_path is None:
        return Config.SQLALCHEMY_DATABASE_URI
    path = Path(db_path).resolve().as_posix()
    return f"sqlite:///{path}"


def _include_object(obj, name, _type, _reflected, _compare_to):
    return not (_type == "table" and name in {"businesses", "products", "rfqs"})


def create_platform_app(legacy_app, db_path=None):
    app = Flask(__name__, template_folder="templates", static_folder=None)
    app.config.from_object(Config)
    app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri(db_path)
    app.config["TESTING"] = db_path is not None
    if app.config["TESTING"]:
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"poolclass": NullPool}
    validate_config(app)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(ROOT / "database" / "migrations"), include_object=_include_object)
    login_manager.init_app(app)
    csrf.init_app(app)

    @event.listens_for(Engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record):
        if connection.__class__.__module__.startswith("sqlite3"):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    with app.app_context():
        if app.config["TESTING"] or app.config["AUTO_CREATE_DB"]:
            db.create_all()
        tables = inspect(db.engine)
        if tables.has_table("businesses"):
            legacy_app.setup()
        if tables.has_table("service_categories"):
            _seed_service_catalog()
        if tables.has_table("users"):
            _provision_admin(app)

    app.extensions["legacy_marketplace"] = legacy_app
    def legacy_method(method):
        def call(*args, **kwargs):
            with app.app_context():
                return method(*args, **kwargs)
        return call

    app.search = legacy_method(legacy_app.search)
    app.rows = legacy_method(legacy_app.rows)
    app.write = legacy_method(legacy_app.write)
    app.estimate = legacy_app.estimate

    def dispatch_legacy(_legacy_path=""):
        path = request.path
        if path == "/dashboard":
            if not current_user.is_authenticated:
                return redirect("/auth/login?next=/dashboard")
            if current_user.role != "ADMIN":
                abort(403)
        if (path == "/business" and request.method == "POST") or path.endswith("/availability") or path.startswith("/rfq/"):
            if not current_user.is_authenticated or current_user.role != "ADMIN":
                abort(403)
        if path == "/api/rfqs" and request.method == "GET":
            if not current_user.is_authenticated or current_user.role != "ADMIN":
                abort(403)
        captured = {}
        payload = b"".join(legacy_app(request.environ, lambda status, headers: captured.update(status=status, headers=headers)))
        return Response(payload, status=captured.get("status", "500 Internal Server Error"), headers=captured.get("headers", []))

    app.add_url_rule("/", "legacy_root", dispatch_legacy, defaults={"_legacy_path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    app.add_url_rule("/<path:_legacy_path>", "legacy_path", dispatch_legacy, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])

    from routes.admin import admin, register_cli
    from routes.auth import auth
    from routes.contractor import contractor
    from routes.jobs import jobs
    from routes.notifications import notifications
    from routes.payments import payments
    from routes.reviews import reviews
    from routes.services import services
    from routes.user import user

    for blueprint in (auth, user, contractor, admin, services, jobs, payments, reviews, notifications):
        app.register_blueprint(blueprint)

    @app.route("/8489415717", methods=["GET", "POST"])
    def private_admin_login():
        """Unlisted admin login entry point."""
        from routes.admin import login as admin_login

        return admin_login()
    register_cli(app)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return ("Request could not be completed.", error.code)

    @app.errorhandler(Exception)
    def handle_unexpected_error(_error):
        app.logger.exception("Unhandled application error")
        return "Something went wrong. Please try again.", 500

    app.extensions["register_blueprint"] = app.register_blueprint
    return app


def _provision_admin(app):
    email = app.config.get("ADMIN_EMAIL", "").strip().lower()
    password = app.config.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    if not valid_email(email) or not valid_password(password):
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must contain valid admin credentials.")
    if User.query.filter_by(role="ADMIN").first():
        return
    if User.query.filter_by(email=email).first():
        raise RuntimeError("ADMIN_EMAIL belongs to an existing non-admin account.")
    admin = User(name=app.config.get("ADMIN_NAME", "NammaBiz Admin").strip()[:120], email=email, role="ADMIN")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


def _seed_service_catalog():
    from models import Service, ServiceCategory

    defaults = {
        "Construction": ("General construction", "Masonry", "Renovation"),
        "Electrical": ("Wiring", "Electrical repair", "Panel installation"),
        "Plumbing": ("Pipe repair", "Bathroom fitting", "Water pump service"),
        "Painting": ("Interior painting", "Exterior painting"),
        "Carpentry": ("Furniture repair", "Door and window work"),
        "Cleaning": ("Home cleaning", "Deep cleaning"),
        "AC repair": ("AC service", "AC installation"),
        "Appliance repair": ("Refrigerator repair", "Washing machine repair"),
        "Interior work": ("Interior design", "Modular installation"),
        "Gardening": ("Garden maintenance", "Landscaping"),
    }
    if ServiceCategory.query.first():
        return
    for name, services in defaults.items():
        category = ServiceCategory(name=name, slug=name.lower().replace(" ", "-"))
        category.services = [Service(name=service) for service in services]
        db.session.add(category)
    db.session.commit()
