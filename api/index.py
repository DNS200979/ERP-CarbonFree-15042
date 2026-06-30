"""Entrypoint que a Vercel detecta para rodar o FastAPI como função serverless."""

from app.api.main import app

__all__ = ["app"]
