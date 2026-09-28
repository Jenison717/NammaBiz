"""Production WSGI entry point for cloud hosting."""

from app import create_app

application = create_app()
app = application
