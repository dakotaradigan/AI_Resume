"""Resume Assistant FastAPI application package.

Layout:
- ``app.main``: application factory and ASGI entrypoint (``app.main:app``).
- ``app.config``: environment-backed settings.
- ``app.routes``: one module per endpoint group.
- Supporting modules: ``session_store``, ``chat_service``, ``llm``,
  ``retrieval``, ``content``, ``identity``, ``security``, ``middleware``.
"""
