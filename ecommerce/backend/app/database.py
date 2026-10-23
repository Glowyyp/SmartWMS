"""
database.py — Configuración de SQLAlchemy para SmartWMS E-Commerce

La DATABASE_URL se inyecta desde variables de entorno, lo que hace
el cambio entre PostgreSQL local y GCP Cloud SQL completamente transparente.

Ejemplos de DATABASE_URL:
  - Local PostgreSQL:   postgresql://user:pass@localhost:5432/smartwms_ecommerce
  - GCP Cloud SQL:      postgresql+pg8000://user:pass@/smartwms_ecommerce?host=/cloudsql/PROJECT:REGION:INSTANCE
  - SQLite (dev):       sqlite:///./ecommerce.db
"""

import os
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.env import load_project_env

load_project_env()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./ecommerce.db"  # Fallback seguro para desarrollo sin PG
)

# Si DATABASE_URL es una ruta relativa de SQLite, resolver a ruta canónica absoluta
# para garantizar que uvicorn, pruebas y scripts apunten siempre a la misma base de datos.
if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:////"):
    raw_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.isabs(raw_path):
        app_dir = os.path.dirname(os.path.abspath(__file__))        # ecommerce/backend/app
        backend_dir = os.path.dirname(app_dir)                     # ecommerce/backend
        root_dir = os.path.dirname(os.path.dirname(backend_dir))   # CAPSTONE
        
        root_db = os.path.join(root_dir, raw_path.lstrip("./\\"))
        backend_db = os.path.join(backend_dir, raw_path.lstrip("./\\"))
        
        if os.path.exists(root_db):
            canonical_file = root_db
        elif os.path.exists(backend_db):
            canonical_file = backend_db
        else:
            canonical_file = root_db
            
        DATABASE_URL = f"sqlite:///{canonical_file.replace(os.sep, '/')}"

# Parámetros específicos de SQLite (necesarios solo en ese driver)
connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False,
        "timeout": 30,  # Esperar hasta 30s si la base de datos está ocupada
    }

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    # Pool optimizado para FastAPI (async workers)
    pool_pre_ping=True,      # Verifica conexiones muertas antes de usarlas
    pool_size=10,            # Conexiones simultáneas base
    max_overflow=20,         # Conexiones extra bajo carga alta
    echo=os.getenv("DEBUG", "false").lower() == "true",  # Log SQL en debug
)

# ─── GARANTÍA ACID PARA SQLITE: FOREIGN KEYS Y WAL MODE ───────────────────────
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Garantiza el cumplimiento ACID en SQLite:
    1. foreign_keys=ON: SQLite por defecto no valida FKs; esto exige integridad referencial.
    2. journal_mode=WAL: Permite múltiples lectores concurrentes sin bloquear escrituras.
    3. synchronous=NORMAL: Durabilidad segura en disco sin degradar rendimiento.
    4. busy_timeout=30000: Evita errores de 'database is locked' bajo concurrencia.
    """
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """
    Dependency de FastAPI para obtener una sesión de BD por request.
    Garantiza que la sesión se cierra aunque ocurra una excepción.

    Uso en endpoint:
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Crea todas las tablas definidas en los modelos ORM. Llamar al startup."""
    # Importar modelos para que Base los registre antes de create_all
    from app.models import order, order_item, inventory, user, work_order  # noqa: F401
    Base.metadata.create_all(bind=engine)
    migrate_schema()


# Columnas agregadas después de la creación inicial de la tabla 'users'.
# create_all() no altera tablas existentes, por eso se agregan aquí de forma
# idempotente (solo ADD COLUMN; nunca se borran ni modifican datos).
_USER_MFA_COLUMNS = {
    "mfa_enabled":            "BOOLEAN NOT NULL DEFAULT 0",
    "mfa_secret_enc":         "TEXT",
    "mfa_pending_secret_enc": "TEXT",
    "mfa_recovery_codes":     "TEXT",
    "mfa_last_used_step":     "INTEGER",
    "mfa_failed_attempts":    "INTEGER NOT NULL DEFAULT 0",
    "mfa_locked_until":       "TIMESTAMP",
    "mfa_enabled_at":         "TIMESTAMP",
}


def migrate_schema() -> list[str]:
    """Agrega columnas faltantes. Devuelve la lista de columnas creadas."""
    added: list[str] = []
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return added
    existing = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        for name, ddl in _USER_MFA_COLUMNS.items():
            if name not in existing:
                if DATABASE_URL.startswith("postgresql"):
                    ddl = ddl.replace("DEFAULT 0", "DEFAULT FALSE") if name == "mfa_enabled" else ddl
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
                added.append(name)
    return added
