from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.database import Base
from app.modules.analysis import viral_models  # noqa: F401
from app.modules.analysis import models as analysis_models  # noqa: F401
from app.modules.content import account_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.modules.metrics import models as metric_models  # noqa: F401
from app.modules.imports import models as import_models  # noqa: F401
from app.modules.models import models as model_config_models  # noqa: F401
from app.modules.style_facts import style_models  # noqa: F401
from app.modules.style_facts import fact_models  # noqa: F401
from app.modules.workspace import models  # noqa: F401


config = context.config

if database_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
