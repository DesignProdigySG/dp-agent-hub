from alembic import context
from sqlmodel import SQLModel

import app.db  # noqa: F401  (registers every table on SQLModel.metadata)
from app.config import get_settings
from app.db import get_engine

target_metadata = SQLModel.metadata


def include_name(name, type_, parent_names) -> bool:
    # LangGraph's checkpointer and store manage their own tables, and knowledge.ensure_vector()
    # adds the optional pgvector column; leave those alone.
    if type_ == "table":
        return name in target_metadata.tables
    return not (type_ == "column" and name == "embedding_vec")


def run_migrations_offline() -> None:
    context.configure(url=get_settings().sqlalchemy_url, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True,
                      include_name=include_name)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, include_name=include_name)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
