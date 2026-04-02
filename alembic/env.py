# alembic/env.py
import sys
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Agregar el directorio raíz al path
sys.path.append(str(Path(__file__).parent.parent))

# Importar tus modelos y configuraciones
from app.database import Base
from app.models import *  # Importa TODOS tus modelos
from app.config import settings

# Configuración de logging
fileConfig(context.config.config_file_name)

# Metadata de SQLAlchemy (TUS TABLAS)
target_metadata = Base.metadata

# Configuración de la URL de la BD
def get_url():
    return settings.SUPABASE_DATABASE_URL

def run_migrations_offline():
    """Corre migraciones en 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Para detectar cambios en tipos de columna
        compare_server_default=True,  # Para detectar cambios en valores por defecto
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Corre migraciones en 'online' mode."""
    configuration = context.config.get_section(context.config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()