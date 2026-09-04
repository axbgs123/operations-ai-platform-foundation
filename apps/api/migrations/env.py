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
from app.modules.imports import capture_models as capture_models  # noqa: F401
from app.modules.models import models as model_config_models  # noqa: F401
from app.modules.risk_rag import models as risk_rag_models  # noqa: F401
from app.modules.style_facts import style_models  # noqa: F401
from app.modules.style_facts import fact_models  # noqa: F401
from app.modules.generation import models as generation_models  # noqa: F401
from app.modules.hotspots import models as hotspot_models  # noqa: F401
from app.modules.exports import models as export_models  # noqa: F401
from app.modules.workspace import models  # noqa: F401
from app.core import observability as observability_models  # noqa: F401
from app.modules.operations_agent import models as operations_agent_models  # noqa: F401
from app.modules.public_data import models as public_data_models  # noqa: F401


config = context.config

if database_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

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
