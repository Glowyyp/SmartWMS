"""
migrate_sqlite_to_postgres.py — Migra los datos de ecommerce.db (SQLite) a PostgreSQL (GCP Cloud SQL)

Uso:
    set TARGET_DATABASE_URL=postgresql+pg8000://smartwms:PASS@127.0.0.1:5432/smartwms_ecommerce
    python scripts/migrate_sqlite_to_postgres.py

Nota:
    Para conectar a Cloud SQL desde tu PC local, inicia primero Cloud SQL Auth Proxy:
        cloud-sql-proxy PROJECT:REGION:smartwms-db --port 5432
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Agregar ecommerce/backend al sys.path para reutilizar los modelos ORM
ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "ecommerce" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.inventory import ProductInventory  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.order_item import OrderItem  # noqa: E402
from app.models.work_order import (  # noqa: E402
    WorkOrder,
    WorkOrderItem,
    WorkOrderPackage,
    WorkOrderStatusHistory,
)

MODELS_IN_ORDER = [
    User,
    ProductInventory,
    Order,
    OrderItem,
    WorkOrder,
    WorkOrderItem,
    WorkOrderPackage,
    WorkOrderStatusHistory,
]


def main() -> int:
    sqlite_path = ROOT_DIR / "ecommerce.db"
    if not sqlite_path.exists():
        print(f"ERROR: No se encontró la base de datos SQLite en {sqlite_path}")
        return 1

    target_url = os.getenv("TARGET_DATABASE_URL", "").strip()
    if not target_url:
        print("ERROR: Define la variable de entorno TARGET_DATABASE_URL con la cadena de conexión PostgreSQL.")
        return 1

    src_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    dst_engine = create_engine(target_url, pool_pre_ping=True)

    print("1. Creando tablas en PostgreSQL destino...")
    Base.metadata.create_all(bind=dst_engine)

    SrcSession = sessionmaker(bind=src_engine)
    DstSession = sessionmaker(bind=dst_engine)

    src_insp = inspect(src_engine)
    src_tables = set(src_insp.get_table_names())

    with SrcSession() as src_db, DstSession() as dst_db:
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            if table_name not in src_tables:
                print(f"   - {table_name}: no existe en SQLite, omitiendo.")
                continue

            existing_count = dst_db.query(model).count()
            if existing_count > 0:
                print(f"   - {table_name}: ya tiene {existing_count} filas en destino, omitiendo.")
                continue

            rows = src_db.query(model).all()
            if not rows:
                print(f"   - {table_name}: 0 filas en SQLite.")
                continue

            cols = [c.name for c in model.__table__.columns]
            for r in rows:
                data = {c: getattr(r, c) for c in cols}
                dst_db.add(model(**data))
            dst_db.commit()
            print(f"   - {table_name}: {len(rows)} filas migradas.")

            # Ajustar secuencia SERIAL en PostgreSQL
            if "id" in cols:
                dst_db.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
                    )
                )
                dst_db.commit()

    print("Migración completada correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
