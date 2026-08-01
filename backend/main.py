"""Deployment-compatibility entrypoint.

The application lives in the ``app`` package; the canonical uvicorn target is
``app.main:app``. This shim keeps existing ``uvicorn main:app`` start commands
(e.g. a Railway dashboard override) working.
"""

from app.main import app

__all__ = ["app"]
