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
    from routes.setup import setup
    from routes.user import user

    for blueprint in (auth, user, contractor, admin, services, jobs, payments, reviews, notifications, setup):
        app.register_blueprint(blueprint)
    register_cli(app)

    @app.context_processor
    def expose_local_setup_link():
        local_request = request.remote_addr in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
        can_setup = False
        if app.config["FLASK_ENV"] != "production" and local_request:
            from models import PlatformSetting

            configured = db.session.get(PlatformSetting, "initial_admin_created")
            has_admin = User.query.filter_by(role="ADMIN").first() is not None
            can_setup = not configured and not has_admin
        return {"show_local_setup_link": can_setup}

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return ("Request could not be completed.", error.code)

    @app.errorhandler(Exception)
    def handle_unexpected_error(_error):
        app.logger.exception("Unhandled application error")
        return "Something went wrong. Please try again.", 500

    app.extensions["register_blueprint"] = app.register_blueprint
    return app


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
