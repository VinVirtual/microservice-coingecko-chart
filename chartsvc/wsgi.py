"""WSGI entry point: ``gunicorn -c gunicorn.conf.py chartsvc.wsgi:app``."""

from .app import create_app

app = create_app()
