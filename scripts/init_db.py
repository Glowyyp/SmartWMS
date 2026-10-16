"""
scripts/init_db.py — Inicialización y verificación de la base de datos de SmartWMS
Crea tablas y usuarios por defecto si la base de datos está vacía o no existe.
"""

import os
import sys

# Agregar paths para importar módulos de backend
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)
backend_dir = os.path.join(root_dir, "ecommerce", "backend")
sys.path.insert(0, backend_dir)

from app.database import Base, engine, SessionLocal
from app.models.user import User
from app.models.inventory import ProductInventory
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderPackage
from app.models.pending_reception import PendingReception
from app.models.order import Order
from app.models.order_item import OrderItem
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def init_database():
    print("=" * 60)
    print("  SmartWMS - Inicializador de Base de Datos")
    print("=" * 60)
    
    # 1. Crear todas las tablas
    print("\n[1/3] Creando tablas si no existen...")
    Base.metadata.create_all(bind=engine)
    print("  -> Tablas verificadas OK.")

    db = SessionLocal()
    try:
        # 2. Verificar usuarios por defecto
        print("\n[2/3] Verificando usuarios esenciales...")
        default_users = [
            ("admin@smartwms.com", "admin123", "Administrador Principal", "admin"),
            ("supervisor@smartwms.com", "supervisor123", "Supervisor Bodega", "supervisor"),
            ("operario@smartwms.com", "operario123", "Operario Logística", "operario"),
        ]

        created_users = 0
        for email, password, name, role in default_users:
            exists = db.query(User).filter(User.email == email).first()
            if not exists:
                hashed = pwd_context.hash(password)
                u = User(
                    email=email,
                    hashed_password=hashed,
                    full_name=name,
                    role=role,
                    is_active=True
                )
                db.add(u)
                created_users += 1
                print(f"  + Creado usuario: {email} (Rol: {role})")

        if created_users > 0:
            db.commit()
            print(f"  -> {created_users} usuario(s) inicial(es) creado(s).")
        else:
            print("  -> Usuarios existentes OK.")

        # 3. Verificar productos base si catálogo está vacío
        print("\n[3/3] Verificando inventario inicial...")
        prod_count = db.query(ProductInventory).count()
        if prod_count == 0:
            sample_products = [
                ProductInventory(
                    sku="SKU-00100",
                    product_name="Teclado Mecánico RGB",
                    stock_quantity=50,
                    unit_price=45.99,
                    reorder_point=10,
                    warehouse_location="PASILLO-A1",
                    weight=1.1,
                    length=45.0,
                    width=15.0,
                    height=4.0,
                    estimated_volume=2700.0
                ),
                ProductInventory(
                    sku="SKU-00200",
                    product_name="Mouse Inalámbrico Pro",
                    stock_quantity=80,
                    unit_price=24.50,
                    reorder_point=15,
                    warehouse_location="PASILLO-A2",
                    weight=0.25,
                    length=12.0,
                    width=7.0,
                    height=4.0,
                    estimated_volume=336.0
                ),
                ProductInventory(
                    sku="SKU-00300",
                    product_name="Monitor Gaming 27''",
                    stock_quantity=20,
                    unit_price=220.00,
                    reorder_point=5,
                    warehouse_location="ZONA-B1",
                    weight=5.4,
                    length=62.0,
                    width=20.0,
                    height=45.0,
                    estimated_volume=55800.0
                )
            ]
            for p in sample_products:
                db.add(p)
            db.commit()
            print("  -> 3 productos de demostración insertados.")
        else:
            print(f"  -> Catalogo existente contiene {prod_count} productos.")

        print("\n" + "=" * 60)
        print("  Base de datos inicializada y lista para usar.")
        print("=" * 60)

    finally:
        db.close()

if __name__ == "__main__":
    init_database()
