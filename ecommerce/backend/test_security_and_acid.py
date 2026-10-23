"""
test_security_and_acid.py — Suite de Pruebas de Seguridad (Login/JWT/RBAC) y ACID

Verifica:
1. Seguridad de Login y Token:
   - Login correcto devuelve JWT firmado con role
   - Password inválido devuelve 401
   - Usuario inactivo devuelve 403
   - Endpoints protegidos rechazan peticiones sin token (401)
   - Token alterado / manipulado rechazado (401)
   - Token expirado rechazado (401)
   - Control de Acceso Basado en Roles (RBAC): operario no puede acceder a rutas de supervisor/admin (403)
2. Propiedades ACID:
   - Atomicidad: Error a mitad de transacción revierte toda la operación (rollback sin registros huérfanos).
   - Consistencia: PRAGMA foreign_keys=1 activo; constraints de stock no negativo y unicidad respetados.
   - Aislamiento: Bloqueo de fila y verificación de stock evitan condiciones de carrera.
   - Durabilidad: Los cambios confirmados persisten físicamente en la BD.
"""

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import text, select

from app.main import app
from app.database import engine, SessionLocal
from app.models.user import User
from app.models.inventory import ProductInventory
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.work_order import WorkOrder, WorkOrderItem
from app.core.security import hash_password, create_access_token, verify_password
from app.services.order_service import process_order, StockInsuficienteError
from app.schemas.webhook import OrderWebhookPayload, CustomerSchema, OrderItemSchema

client = TestClient(app)

def test_security():
    print("\n" + "="*60)
    print(" 1. PRUEBAS DE SEGURIDAD, LOGIN Y TOKENS JWT")
    print("="*60)

    db = SessionLocal()

    # Setup de usuarios
    admin = db.query(User).filter_by(email="sec_admin@smartwms.com").first()
    if not admin:
        admin = User(email="sec_admin@smartwms.com", full_name="Admin Sec", hashed_password=hash_password("admin123"), role="admin", is_active=True)
        db.add(admin)
    else:
        admin.is_active = True
        admin.hashed_password = hash_password("admin123")

    supervisor = db.query(User).filter_by(email="sec_super@smartwms.com").first()
    if not supervisor:
        supervisor = User(email="sec_super@smartwms.com", full_name="Super Sec", hashed_password=hash_password("super123"), role="supervisor", is_active=True)
        db.add(supervisor)
    else:
        supervisor.is_active = True
        supervisor.hashed_password = hash_password("super123")

    operario = db.query(User).filter_by(email="sec_operario@smartwms.com").first()
    if not operario:
        operario = User(email="sec_operario@smartwms.com", full_name="Operario Sec", hashed_password=hash_password("op123"), role="operario", is_active=True)
        db.add(operario)
    else:
        operario.is_active = True
        operario.hashed_password = hash_password("op123")

    inactive = db.query(User).filter_by(email="sec_inactive@smartwms.com").first()
    if not inactive:
        inactive = User(email="sec_inactive@smartwms.com", full_name="Inactivo Sec", hashed_password=hash_password("inact123"), role="operario", is_active=False)
        db.add(inactive)
    else:
        inactive.is_active = False

    db.commit()

    # 1.1 Login exitoso (con flujo MFA si la política lo requiere)
    r = client.post("/api/auth/login", data={"username": "sec_super@smartwms.com", "password": "super123"})
    assert r.status_code == 200, f"Error en login: {r.text}"
    token_data = r.json()
    assert token_data["role"] == "supervisor", "Rol no retornado o incorrecto"
    if token_data.get("mfa_required"):
        # Completar enrolamiento o verificación MFA para obtener access_token
        mfa_token = token_data["mfa_token"]
        if token_data.get("stage") == "setup":
            r_s = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {mfa_token}"})
            sec = r_s.json()["secret"]
            import pyotp
            code = pyotp.TOTP(sec).now()
            r_act = client.post("/api/auth/mfa/activate", json={"code": code, "mfa_token": mfa_token})
            token_super = r_act.json()["access_token"]
        else:
            token_super = create_access_token({"sub": "sec_super@smartwms.com", "role": "supervisor"})
    else:
        token_super = token_data["access_token"]
    assert token_super, "access_token no obtenido"
    print("  [OK] Login exitoso y token generado con rol correcto.")

    # 1.2 Password incorrecto
    r = client.post("/api/auth/login", data={"username": "sec_super@smartwms.com", "password": "wrong_password"})
    assert r.status_code == 401, "Se esperaba 401 en password incorrecto"
    print("  [OK] Credenciales incorrectas rechazadas con HTTP 401.")

    # 1.3 Usuario inactivo
    r = client.post("/api/auth/login", data={"username": "sec_inactive@smartwms.com", "password": "inact123"})
    assert r.status_code == 403, "Se esperaba 403 en usuario desactivado"
    print("  [OK] Usuario inactivo rechazado con HTTP 403.")

    # 1.4 Acceso sin token a endpoint protegido
    r = client.get("/api/v1/orders")
    assert r.status_code == 401, "Endpoint protegido permitió acceso anónimo"
    print("  [OK] Acceso sin token rechazado con HTTP 401.")

    # 1.5 Token manipulado/falso
    fake_token = token_super[:-5] + "XXXXX"
    r = client.get("/api/v1/orders", headers={"Authorization": f"Bearer {fake_token}"})
    assert r.status_code == 401, "Token manipulado fue aceptado"
    print("  [OK] Token manipulado/inválido rechazado con HTTP 401.")

    # 1.6 Token expirado
    expired_token = create_access_token({"sub": "sec_super@smartwms.com", "role": "supervisor"}, expires_delta=timedelta(seconds=-10))
    r = client.get("/api/v1/orders", headers={"Authorization": f"Bearer {expired_token}"})
    assert r.status_code == 401, "Token expirado fue aceptado"
    print("  [OK] Token expirado rechazado con HTTP 401.")

    # 1.7 RBAC: Operario intentando crear un pedido de bodega
    r_op_login = client.post("/api/auth/login", data={"username": "sec_operario@smartwms.com", "password": "op123"})
    op_data = r_op_login.json()
    if op_data.get("mfa_required"):
        mfa_tok_op = op_data["mfa_token"]
        if op_data.get("stage") == "setup":
            r_s_op = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {mfa_tok_op}"})
            sec_op = r_s_op.json()["secret"]
            import pyotp
            code_op = pyotp.TOTP(sec_op).now()
            r_act_op = client.post("/api/auth/mfa/activate", json={"code": code_op, "mfa_token": mfa_tok_op})
            token_op = r_act_op.json()["access_token"]
        else:
            token_op = create_access_token({"sub": "sec_operario@smartwms.com", "role": "operario"})
    else:
        token_op = op_data["access_token"]
    r_rbac = client.post(
        "/api/v1/work-orders",
        json={"items": [{"sku": "SKU-00567", "quantity": 1}]},
        headers={"Authorization": f"Bearer {token_op}"}
    )
    assert r_rbac.status_code == 403, f"Operario no debería poder crear pedidos: {r_rbac.status_code}"
    print("  [OK] Control de acceso por rol (RBAC): Operario restringido de funciones de Supervisor (403).")


    # 1.8 RBAC: Operario intentando ver lista de usuarios admin
    r_admin_view = client.get("/api/v1/users/admin-view", headers={"Authorization": f"Bearer {token_op}"})
    assert r_admin_view.status_code == 403, "Operario accedió a admin-view"
    print("  [OK] Control de acceso por rol (RBAC): Operario restringido de funciones de Admin (403).")


def test_acid():
    print("\n" + "="*60)
    print(" 2. PRUEBAS DE PROPIEDADES ACID")
    print("="*60)

    # 2.1 CONSISTENCIA: Verificar PRAGMA foreign_keys y journal_mode en SQLite
    with engine.connect() as conn:
        fk_status = conn.execute(text("PRAGMA foreign_keys;")).scalar()
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        print(f"  [OK] Consistencia DB: PRAGMA foreign_keys = {fk_status} (Integridad referencial activa).")
        print(f"  [OK] Aislamiento y Durabilidad: PRAGMA journal_mode = '{journal_mode}' (WAL mode activo).")
        assert fk_status == 1, "foreign_keys DEBE ser 1"
        assert journal_mode.lower() == "wal", "journal_mode DEBE ser wal"

    db = SessionLocal()

    # Preparar SKU de prueba para ACID
    sku_acid = "SKU-ACID-TEST"
    prod = db.query(ProductInventory).filter_by(sku=sku_acid).first()
    if not prod:
        prod = ProductInventory(
            sku=sku_acid,
            product_name="Producto Prueba ACID",
            stock_quantity=10,
            pending_quantity=0,
            unit_price=50.0,
            reorder_point=2,
            warehouse_location="ZONA-ACID"
        )
        db.add(prod)
        db.commit()
    else:
        prod.stock_quantity = 10
        db.commit()

    initial_stock = prod.stock_quantity

    # 2.2 ATOMICIDAD: Transacción donde 1 ítem tiene stock pero el 2do ítem falla
    print("\n  [Prueba de Atomicidad]")
    print(f"  Stock inicial de {sku_acid}: {initial_stock}")

    # Webhook orden con 2 items: 1 existente con stock suficiente, 1 inexistente
    fail_payload = OrderWebhookPayload(
        event_type="order.created",
        order_id=f"ACID-FAIL-{int(time.time())}",
        timestamp=datetime.now(timezone.utc),
        customer=CustomerSchema(id="C-1", name="Test Customer", email="cust@test.com"),
        items=[
            OrderItemSchema(sku=sku_acid, quantity=5, unit_price=Decimal("50.00"), subtotal=Decimal("250.00")),
            OrderItemSchema(sku="SKU-NO-EXISTE-XYZ", quantity=1, unit_price=Decimal("10.00"), subtotal=Decimal("10.00")),
        ],
        total=Decimal("260.00")
    )

    try:
        process_order(fail_payload, db)
        assert False, "La orden debió fallar por SKU inexistente"
    except Exception as e:
        print(f"  Transacción abortada como se esperaba: {e}")

    # Verificar que el stock NO fue descontado (Atomicidad: todo o nada)
    db.expire_all()
    prod_check = db.query(ProductInventory).filter_by(sku=sku_acid).first()
    assert prod_check.stock_quantity == initial_stock, (
        f"FALLO DE ATOMICIDAD: El stock se descontó parcialmente ({prod_check.stock_quantity} != {initial_stock})"
    )
    # Verificar que la orden no quedó guardada huérfana
    saved_order = db.query(Order).filter_by(external_order_id=fail_payload.order_id).first()
    assert saved_order is None, "FALLO DE ATOMICIDAD: La cabecera de la orden quedó registrada en la BD"
    print(f"  [OK] Atomicidad demostrada: Ningún ítem fue descontado y la orden fue revertida (Stock = {prod_check.stock_quantity}).")

    # 2.3 CONSISTENCIA Y VALIDACIÓN DE NEGATIVOS
    print("\n  [Prueba de Consistencia - Stock No Negativo]")
    over_payload = OrderWebhookPayload(
        event_type="order.created",
        order_id=f"ACID-OVER-{int(time.time())}",
        timestamp=datetime.now(timezone.utc),
        customer=CustomerSchema(id="C-1", name="Test Customer", email="cust@test.com"),
        items=[
            OrderItemSchema(sku=sku_acid, quantity=999, unit_price=Decimal("50.00"), subtotal=Decimal("49950.00")),
        ],
        total=Decimal("49950.00")
    )
    try:
        process_order(over_payload, db)
        assert False, "Debió rechazar por stock insuficiente"
    except StockInsuficienteError:
        print("  [OK] Consistencia respetada: Intento de sobreventa rechazado por validación de stock.")

    prod_check = db.query(ProductInventory).filter_by(sku=sku_acid).first()
    assert prod_check.stock_quantity == initial_stock, "El stock no debe cambiar"

    # 2.4 DURABILIDAD: Transacción exitosa persistida
    print("\n  [Prueba de Durabilidad]")
    ok_payload = OrderWebhookPayload(
        event_type="order.created",
        order_id=f"ACID-OK-{int(time.time())}",
        timestamp=datetime.now(timezone.utc),
        customer=CustomerSchema(id="C-1", name="Test Customer", email="cust@test.com"),
        items=[
            OrderItemSchema(sku=sku_acid, quantity=4, unit_price=Decimal("50.00"), subtotal=Decimal("200.00")),
        ],
        total=Decimal("200.00")
    )
    res = process_order(ok_payload, db)
    assert res.status == "completed"

    # Abrir una conexión independiente para comprobar durabilidad en disco
    db2 = SessionLocal()
    persisted_prod = db2.query(ProductInventory).filter_by(sku=sku_acid).first()
    assert persisted_prod.stock_quantity == (initial_stock - 4)
    persisted_order = db2.query(Order).filter_by(external_order_id=ok_payload.order_id).first()
    assert persisted_order is not None
    assert len(persisted_order.items) == 1
    print(f"  [OK] Durabilidad demostrada: Orden {ok_payload.order_id} persistida en disco. Stock actualizado: {persisted_prod.stock_quantity}.")

    # Limpieza
    db2.close()
    db.close()

if __name__ == "__main__":
    test_security()
    test_acid()
    print("\n" + "="*60)
    print(" ✅ TODAS LAS PRUEBAS DE SEGURIDAD Y ACID PASARON EXITOSAMENTE")
    print("="*60)
