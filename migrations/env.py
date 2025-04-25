import os
import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

# Setup logging
config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# Get your database engine (works with Flask-SQLAlchemy<3 and >=3)
def get_engine():
    try:
        return current_app.extensions["migrate"].db.get_engine()
    except (TypeError, AttributeError):
        return current_app.extensions["migrate"].db.engine

# Generate the DB URL (make sure password characters don't mess things up)
def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace('%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')

# Set the sqlalchemy URL so Alembic knows where to migrate
import os

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable not set")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


# Get the db instance from app.py
target_db = current_app.extensions["migrate"].db

# Get metadata for autogenerate
def get_metadata():
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas[None]
    return target_db.metadata

# Run offline migration (no DB connection needed)
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=get_metadata(), literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()

# Run online migration (connect to DB)
def run_migrations_online():
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    conf_args = current_app.extensions["migrate"].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=get_metadata(), **conf_args)

        with context.begin_transaction():
            context.run_migrations()

# Decide based on context
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
