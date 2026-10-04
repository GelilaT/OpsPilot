"""Procrastinate application: jobs live in PostgreSQL (FR-JOB-01).

Run a worker with:  procrastinate --app=app.workers.app.app worker
"""

import procrastinate

import app.models  # register every ORM model so foreign keys resolve in the worker
from app.adapters import register_all
from app.core.integrations import registry
from app.core.settings import get_settings

register_all(registry, get_settings())

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo),
    import_paths=["app.workers.tasks"],
)
