import os
import sys
import sqlite3

# Añadir ruta al sys.path para importar módulos de la app
sys.path.append(os.path.join(os.path.dirname(__file__), "ecommerce", "backend"))

from app.database import engine, Base
# Importar todos los modelos para que Base.metadata los reconozca
from app.models import *

def migrate():
    db_path = os.path.join(os.path.dirname(__file__), "ecommerce", "backend", "ecommerce.db")
    
    # 1. Crear nuevas tablas (pending_receptions, work_order_packages)
    print("Creando nuevas tablas si no existen...")
    Base.metadata.create_all(bind=engine)
    print("Tablas verificadas/creadas.")

    # 2. Añadir nuevas columnas a tablas existentes usando sqlite3 puro
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # --- Actualizar product_inventory ---
    c.execute("PRAGMA table_info(product_inventory)")
    inv_cols = [row[1] for row in c.fetchall()]

    inv_new_columns = [
        ("pending_quantity", "INTEGER NOT NULL DEFAULT 0"),
        ("length", "NUMERIC(10, 2)"),
        ("width", "NUMERIC(10, 2)"),
        ("height", "NUMERIC(10, 2)"),
        ("dimensions_unit", "VARCHAR(10) NOT NULL DEFAULT 'cm'"),
        ("weight", "NUMERIC(10, 3)"),
        ("weight_unit", "VARCHAR(10) NOT NULL DEFAULT 'kg'"),
        ("has_box", "BOOLEAN NOT NULL DEFAULT 1")
    ]

    for col_name, col_type in inv_new_columns:
        if col_name not in inv_cols:
            try:
                c.execute(f"ALTER TABLE product_inventory ADD COLUMN {col_name} {col_type}")
                print(f"Columna {col_name} añadida a product_inventory.")
            except Exception as e:
                print(f"Error al añadir {col_name} a product_inventory: {e}")

    # --- Actualizar work_orders ---
    c.execute("PRAGMA table_info(work_orders)")
    wo_cols = [row[1] for row in c.fetchall()]

    wo_new_columns = [
        ("total_weight", "NUMERIC(10, 3)"),
        ("total_volume", "NUMERIC(10, 2)"),
        ("packages_count", "INTEGER NOT NULL DEFAULT 0")
    ]

    for col_name, col_type in wo_new_columns:
        if col_name not in wo_cols:
            try:
                c.execute(f"ALTER TABLE work_orders ADD COLUMN {col_name} {col_type}")
                print(f"Columna {col_name} añadida a work_orders.")
            except Exception as e:
                print(f"Error al añadir {col_name} a work_orders: {e}")

    conn.commit()
    conn.close()
    print("Migración completada exitosamente.")

if __name__ == "__main__":
    migrate()
