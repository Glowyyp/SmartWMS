"""
scripts/update_product_weights_volumes.py
Actualiza la base de datos agregando peso, dimensiones y volumen estimado a los productos existentes.
"""

import sqlite3
import os

products_specs = [
    {
        "sku": "SKU-00567",
        "name": "Teclado Mecánico RGB",
        "length": 44.5, "width": 14.0, "height": 4.0,
        "weight": 0.950, "estimated_volume": 2492.0,
    },
    {
        "sku": "SKU-00412",
        "name": "Tornillo M8 Acero",
        "length": 5.0, "width": 1.2, "height": 1.2,
        "weight": 0.025, "estimated_volume": 7.2,
    },
    {
        "sku": "SKU-00891",
        "name": "Cable USB-C 2m",
        "length": 15.0, "width": 8.0, "height": 2.5,
        "weight": 0.080, "estimated_volume": 300.0,
    },
    {
        "sku": "SKU-01234",
        "name": 'Monitor 27" 144Hz',
        "length": 61.5, "width": 18.0, "height": 45.0,
        "weight": 4.850, "estimated_volume": 49815.0,
    },
    {
        "sku": "SKU-01567",
        "name": "Mousepad XL Gaming",
        "length": 90.0, "width": 40.0, "height": 0.4,
        "weight": 0.650, "estimated_volume": 1440.0,
    },
    {
        "sku": "SKU-01890",
        "name": "Auriculares Inalámbricos",
        "length": 20.0, "width": 18.0, "height": 8.5,
        "weight": 0.320, "estimated_volume": 3060.0,
    },
    {
        "sku": "SKU-676767",
        "name": "G403",
        "length": 12.4, "width": 6.8, "height": 4.3,
        "weight": 0.090, "estimated_volume": 362.56,
    },
    {
        "sku": "SKU-TEST-5",
        "name": "Test Product 5",
        "length": 25.0, "width": 15.0, "height": 10.0,
        "weight": 1.200, "estimated_volume": 3750.0,
    },
    {
        "sku": "sku-8585",
        "name": "g203",
        "length": 11.6, "width": 6.2, "height": 3.8,
        "weight": 0.085, "estimated_volume": 273.3,
    },
]

def migrate_db(db_path):
    if not os.path.exists(db_path):
        print(f"[SKIP] No existe la base de datos en {db_path}")
        return
    print(f"\n[+] Actualizando base de datos: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Verificar si existe la columna estimated_volume
    c.execute("PRAGMA table_info(product_inventory)")
    cols = [r[1] for r in c.fetchall()]
    if "estimated_volume" not in cols:
        print("  -> Agregando columna 'estimated_volume'...")
        c.execute("ALTER TABLE product_inventory ADD COLUMN estimated_volume NUMERIC(12, 2)")
    
    # Actualizar cada producto
    updated_count = 0
    for p in products_specs:
        c.execute("""
            UPDATE product_inventory 
            SET length = ?, width = ?, height = ?, weight = ?, estimated_volume = ?
            WHERE LOWER(sku) = LOWER(?)
        """, (p["length"], p["width"], p["height"], p["weight"], p["estimated_volume"], p["sku"]))
        if c.rowcount > 0:
            updated_count += c.rowcount
            print(f"  -> {p['sku']}: Peso={p['weight']}kg, Vol={p['estimated_volume']}cm³")
            
    conn.commit()
    conn.close()
    print(f"[OK] {updated_count} productos actualizados con éxito en {db_path}")

if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_root = os.path.join(root_dir, "ecommerce.db")
    db_backend = os.path.join(root_dir, "ecommerce", "backend", "ecommerce.db")

    migrate_db(db_root)
    migrate_db(db_backend)
