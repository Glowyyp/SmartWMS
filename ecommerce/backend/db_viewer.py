"""
db_viewer.py — Inspector de base de datos SQLite para SmartWMS

Imprime en consola las tablas: users, product_inventory y orders.

Uso:
    cd ecommerce/backend
    python db_viewer.py
"""

import os
import sys
from pathlib import Path

# Aseguramos que el paquete 'app' esté en el path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ecommerce.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})


def print_table(title: str, headers: list[str], rows: list) -> None:
    """Imprime una tabla con bordes ASCII."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell) if cell is not None else "NULL"))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    fmt = "|" + "|".join(f" {{:<{w}}} " for w in col_widths) + "|"

    print(f"\n{'-' * 10} {title} {'-' * 10}")
    print(sep)
    print(fmt.format(*headers))
    print(sep)
    if rows:
        for row in rows:
            print(fmt.format(*[str(c) if c is not None else "NULL" for c in row]))
    else:
        total_width = sum(col_widths) + len(col_widths) * 3 + 1
        print("|" + " (sin registros)".center(total_width - 2) + "|")
    print(sep)
    print(f"  {len(rows)} registro(s)\n")


def main():
    with engine.connect() as conn:

        # ── users ──────────────────────────────────────────────────────────────
        result = conn.execute(text(
            "SELECT id, email, full_name, role, is_active, created_at FROM users ORDER BY id"
        ))
        rows = result.fetchall()
        print_table(
            "USERS",
            ["id", "email", "full_name", "role", "is_active", "created_at"],
            rows,
        )

        # ── product_inventory ──────────────────────────────────────────────────
        result = conn.execute(text(
            "SELECT id, sku, product_name, stock_quantity, unit_price, reorder_point, updated_at "
            "FROM product_inventory ORDER BY sku"
        ))
        rows = result.fetchall()
        print_table(
            "PRODUCT_INVENTORY",
            ["id", "sku", "product_name", "stock", "price", "reorder_pt", "updated_at"],
            rows,
        )

        # ── orders ─────────────────────────────────────────────────────────────
        result = conn.execute(text(
            "SELECT id, external_order_id, customer_email, status, total, received_at "
            "FROM orders ORDER BY id DESC LIMIT 20"
        ))
        rows = result.fetchall()
        print_table(
            "ORDERS (ultimas 20)",
            ["id", "external_order_id", "customer_email", "status", "total", "received_at"],
            rows,
        )


if __name__ == "__main__":
    main()
