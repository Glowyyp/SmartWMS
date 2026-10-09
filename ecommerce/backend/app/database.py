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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./ecommerce.db"  # Fallback seguro para desarrollo sin PG
)

# Parámetros específicos de SQLite (necesarios solo en ese driver)
connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    # Pool optimizado para FastAPI (async workers)
    pool_pre_ping=True,      # Verifica conexiones muertas antes de usarlas
    pool_size=10,            # Conexiones simultáneas base
    max_overflow=20,         # Conexiones extra bajo carga alta
    echo=os.getenv("DEBUG", "false").lower() == "true",  # Log SQL en debug
)

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
