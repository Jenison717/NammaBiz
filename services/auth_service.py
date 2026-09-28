import smtplib
from hmac import compare_digest
from email.message import EmailMessage

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import User


def make_reset_token(user):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).dumps(
        {"email": user.email, "password_hash": user.password_hash}, salt="password-reset"
    )


def read_reset_token(token, max_age=1800):
    try:
        payload = URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).loads(token, salt="password-reset", max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    user = User.query.filter_by(email=payload.get("email"), active=True).first()
    if not user or not compare_digest(user.password_hash, payload.get("password_hash", "")):
        return None
    return user.email


def send_reset_email(email, url):
    config = current_app.config
    if current_app.testing:
        current_app.extensions.setdefault("mail_outbox", []).append({"to": email, "url": url})
        return True
    if not config.get("MAIL_SERVER"):
        current_app.logger.warning("Password reset requested but mail delivery is not configured.")
        return False
    message = EmailMessage()
    message["Subject"] = "Reset your NammaBiz password"
    message["From"] = config["MAIL_DEFAULT_SENDER"]
    message["To"] = email
    message.set_content(f"Use this one-time link within 30 minutes to reset your password:\n\n{url}\n")
    with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=15) as server:
        server.starttls()
        if config.get("MAIL_USERNAME"):
            server.login(config["MAIL_USERNAME"], config.get("MAIL_PASSWORD", ""))
        server.send_message(message)
    return True
