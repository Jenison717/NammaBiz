import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class Config:
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'nammabiz.sqlite3').as_posix()}"
    )
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql+psycopg://", 1)
    elif SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgresql://", "postgresql+psycopg://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_DB = os.environ.get("AUTO_CREATE_DB", "true").lower() == "true"
    SEED_SAMPLE_DATA = os.environ.get("SEED_SAMPLE_DATA", "false" if FLASK_ENV == "production" else "true").lower() == "true"
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "NammaBiz Admin")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", ROOT / "uploads"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    WTF_CSRF_TIME_LIMIT = 3600
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "NammaBiz <no-reply@nammabiz.local>")
    PAYMENT_MODE = os.environ.get("PAYMENT_MODE", "disabled").lower()
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    TESTING = False


def validate_config(app):
    if app.config.get("FLASK_ENV") == "production" and app.config["SECRET_KEY"] == "local-development-only-change-me":
        raise RuntimeError("Set SECRET_KEY in the production environment.")
    if app.config.get("FLASK_ENV") == "production" and (not app.config.get("ADMIN_EMAIL") or not app.config.get("ADMIN_PASSWORD")):
        raise RuntimeError("Set ADMIN_EMAIL and ADMIN_PASSWORD in the production environment.")
