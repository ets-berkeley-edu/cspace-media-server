"""ASGI entry point: uvicorn serena.main:app --no-access-log"""
from .app import create_app

app = create_app()
