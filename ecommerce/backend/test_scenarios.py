"""
test_scenarios.py — Pruebas de los 7 escenarios de gestión de pedidos y asignación de operarios.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.inventory import ProductInventory
from app.models.work_order import WorkOrder
from app.core.security import hash_password

client = TestClient(app)

def get_or_create_user(db, email, full_name, role):
    user = db.query(User).filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password("admin123"),
            role=role,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.hashed_password = hash_password("admin123")
        user.is_active = True
        user.role = role
        db.commit()
    return user

def get_or_create_product(db, sku, name, stock, unit_price):
    prod = db.query(ProductInventory).filter_by(sku=sku).first()
    if not prod:
        prod = ProductInventory(
            sku=sku,
            product_name=name,
            stock_quantity=stock,
            pending_quantity=0,
            unit_price=unit_price,
            reorder_point=5,
            warehouse_location="ZONA-A"
        )
        db.add(prod)
        db.commit()
        db.refresh(prod)
    else:
        prod.stock_quantity = max(prod.stock_quantity, stock)
        prod.unit_price = unit_price
        db.commit()
    return prod

def get_token(username, password="admin123"):
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    body = resp.json()
    if body.get("access_token"):
        return body["access_token"]
    
    if body.get("mfa_required"):
        mfa_token = body.get("mfa_token")
        stage = body.get("stage")
        import pyotp
        from app.core.mfa import decrypt_secret
        if stage == "setup":
            s_res = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {mfa_token}"})
            secret = s_res.json()["secret"]
            code = pyotp.TOTP(secret).now()
            act_res = client.post("/api/auth/mfa/activate", json={"code": code}, headers={"Authorization": f"Bearer {mfa_token}"})
            return act_res.json()["access_token"]
        elif stage == "verify":
            with SessionLocal() as db:
                user = db.query(User).filter(User.email == username).first()
                user.mfa_last_used_step = None
                user.mfa_failed_attempts = 0
                user.mfa_locked_until = None
                db.commit()
                secret = decrypt_secret(user.mfa_secret_enc)
                code = pyotp.TOTP(secret).now()
            v_res = client.post("/api/auth/mfa/verify", json={"code": code}, headers={"Authorization": f"Bearer {mfa_token}"})
            return v_res.json()["access_token"]
    return body.get("access_token")

def run_tests():
    db = SessionLocal()

    # Usuarios para pruebas
    super_user = get_or_create_user(db, "supervisor@smartwms.com", "Supervisor Principal", "supervisor")
    op_logistica = get_or_create_user(db, "operario@smartwms.com", "Operario Logística", "operario")
    op_secundario = get_or_create_user(db, "estoylol@gmail.com", "Operario Secundario", "operario")

    # Productos con stock disponible
    p1 = get_or_create_product(db, "SKU-SCENARIO-1", "Teclado Test", 100, 25.0)
    p2 = get_or_create_product(db, "SKU-SCENARIO-2", "Mouse Test", 100, 15.0)

    token_super = get_token("supervisor@smartwms.com")
    token_op1 = get_token("operario@smartwms.com")
    token_op2 = get_token("estoylol@gmail.com")

    headers_super = {"Authorization": f"Bearer {token_super}"}
    headers_op1 = {"Authorization": f"Bearer {token_op1}"}
    headers_op2 = {"Authorization": f"Bearer {token_op2}"}

    print("\n=== Escenario 1: Crear pedido sin operario (debe ser 'por_asignar') ===")
    resp = client.post(
        "/api/v1/work-orders",
        json={
            "items": [{"sku": "SKU-SCENARIO-1", "quantity": 2}]
        },
        headers=headers_super
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    order_id = order["id"]
    assert order["status"] == "por_asignar", f"Esperado 'por_asignar', obtenido: {order['status']}"
    assert order["assigned_operario_id"] is None
    assert order["assigned_operario_email"] is None
    print(f"OK: Pedido {order['order_number']} creado con estado '{order['status']}'")

    print("\n=== Escenario 2: Asignarlo al operario de Logística (debe ser 'pending' y aparecer en su cuenta) ===")
    resp = client.put(
        f"/api/v1/work-orders/{order_id}/assign",
        json={
            "assigned_operario_id": op_logistica.id,
            "assigned_operario_email": op_logistica.email
        },
        headers=headers_super
    )
    assert resp.status_code == 200, resp.text
    assigned_order = resp.json()
    assert assigned_order["status"] == "pending", f"Esperado 'pending', obtenido: {assigned_order['status']}"
    assert assigned_order["assigned_operario_id"] == op_logistica.id
    assert assigned_order["assigned_operario_email"] == op_logistica.email
    print(f"OK: Pedido {assigned_order['order_number']} asignado a {op_logistica.email} con estado '{assigned_order['status']}'")

    # Verificar que aparece en la cuenta del operario de Logística
    resp_op1 = client.get("/api/v1/work-orders", headers=headers_op1)
    assert resp_op1.status_code == 200
    op1_order_ids = [o["id"] for o in resp_op1.json()]
    assert order_id in op1_order_ids, "El pedido no aparece en la cuenta del operario de Logística"
    print(f"OK: Pedido {order_id} visible en panel de Operario Logística")

    print("\n=== Escenario 3: Iniciar sesión como otro operario (no debe aparecer como asignado a él) ===")
    resp_op2 = client.get("/api/v1/work-orders", headers=headers_op2)
    assert resp_op2.status_code == 200
    op2_order_ids = [o["id"] for o in resp_op2.json()]
    assert order_id not in op2_order_ids, "El pedido NO debería aparecer en la cuenta del otro operario"
    print(f"OK: Pedido {order_id} NO es visible para Operario Secundario")

    print("\n=== Escenario 4: Reasignar un pedido pendiente de un operario a otro ===")
    resp_reassign = client.put(
        f"/api/v1/work-orders/{order_id}/assign",
        json={
            "assigned_operario_id": op_secundario.id,
            "assigned_operario_email": op_secundario.email
        },
        headers=headers_super
    )
    assert resp_reassign.status_code == 200
    assert resp_reassign.json()["assigned_operario_id"] == op_secundario.id

    # Debe aparecer en la cuenta del nuevo operario
    resp_op2_new = client.get("/api/v1/work-orders", headers=headers_op2)
    assert order_id in [o["id"] for o in resp_op2_new.json()], "Debe aparecer en Operario Secundario"

    # Y dejar de aparecer en la cuenta del anterior
    resp_op1_new = client.get("/api/v1/work-orders", headers=headers_op1)
    assert order_id not in [o["id"] for o in resp_op1_new.json()], "Debe dejar de aparecer en Operario Logística"
    print("OK: Reasignación exitosa y reflejada exclusivamente en el nuevo operario")

    print("\n=== Escenario 5: Editar los items y cantidades (detalle y total actualizados) ===")
    resp_edit_items = client.put(
        f"/api/v1/work-orders/{order_id}",
        json={
            "items": [
                {"sku": "SKU-SCENARIO-1", "quantity": 4},
                {"sku": "SKU-SCENARIO-2", "quantity": 3}
            ]
        },
        headers=headers_super
    )
    assert resp_edit_items.status_code == 200, resp_edit_items.text
    edited_order = resp_edit_items.json()
    assert len(edited_order["items"]) == 2
    assert edited_order["total_items"] == 7  # 4 + 3
    # Total esperado: (4 * 25.0) + (3 * 15.0) = 100.0 + 45.0 = 145.0
    assert edited_order["total_amount"] == 145.0, f"Total esperado 145.0, obtenido {edited_order['total_amount']}"
    print(f"OK: Items actualizados correctamente. Total items: {edited_order['total_items']}, Total monto: ${edited_order['total_amount']}")

    print("\n=== Escenario 6: Cambiar el estado desde el formulario de edición ===")
    resp_edit_status = client.put(
        f"/api/v1/work-orders/{order_id}",
        json={
            "status": "in_preparation"
        },
        headers=headers_super
    )
    assert resp_edit_status.status_code == 200
    assert resp_edit_status.json()["status"] == "in_preparation"
    print("OK: Estado actualizado a 'in_preparation'")

    print("\n=== Escenario 7: Editar pedido en proceso (cambiar operario no lo reinicia a 'pending') ===")
    resp_edit_in_proc = client.put(
        f"/api/v1/work-orders/{order_id}",
        json={
            "assigned_operario_id": op_logistica.id,
            "assigned_operario_email": op_logistica.email
        },
        headers=headers_super
    )
    assert resp_edit_in_proc.status_code == 200
    order_in_proc = resp_edit_in_proc.json()
    assert order_in_proc["assigned_operario_email"] == op_logistica.email
    assert order_in_proc["status"] == "in_preparation", f"El estado cambió inesperadamente a '{order_in_proc['status']}'"
    print("OK: Pedido en proceso reasignado sin alterar su estado ('in_preparation' conservado)")

    print("\n=== Validación adicional: Desasignar pedido pendiente vuelve a 'por_asignar' ===")
    # Crear otro pedido con operario
    resp_p = client.post(
        "/api/v1/work-orders",
        json={
            "items": [{"sku": "SKU-SCENARIO-1", "quantity": 1}],
            "assigned_operario_id": op_logistica.id
        },
        headers=headers_super
    )
    assert resp_p.status_code == 201
    wo_unassign_id = resp_p.json()["id"]
    assert resp_p.json()["status"] == "pending"

    # Desasignar
    resp_un = client.put(
        f"/api/v1/work-orders/{wo_unassign_id}/assign",
        json={"assigned_operario_id": None, "assigned_operario_email": None},
        headers=headers_super
    )
    assert resp_un.status_code == 200
    assert resp_un.json()["status"] == "por_asignar"
    assert resp_un.json()["assigned_operario_id"] is None
    print("OK: Pedido desasignado vuelve a 'por_asignar'")

    print("\n>>> TODOS LOS 7 ESCENARIOS Y VALIDACIONES PASARON EXITOSAMENTE <<<\n")

if __name__ == "__main__":
    run_tests()
