"""Alembic environment. Autogenerate only compares the schema being migrated."""

import os

from alembic import context
from sqlalchemy import create_engine

from kernel.db import Base
from kernel.registry import import_all_models

KERNEL_SCHEMAS = {"core", "trust", "ai"}

import_all_models()


def scope_schemas() -> set[str]:
    scope = os.environ.get("ALEMBIC_SCOPE", "kernel")
    if scope == "kernel":
        return KERNEL_SCHEMAS | {"knowledge", "comms", "calendar"}
    return {scope}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in scope_schemas()
    return True


def run() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="core",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run()
