from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.inventory import ProductInventory
from app.core.security import hash_password

client = TestClient(app)

def create_user(db, email, role):
    user = db.query(User).filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            hashed_password=hash_password("admin123"),
            role=role,
            is_active=True
        )
        db.add(user)
        db.commit()
    return user

def get_token(username, password):
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
        from app.models.user import User
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

def main():
    print("Iniciando pruebas de la Fase 5...")
    
    db = SessionLocal()
    # Crear usuarios
    create_user(db, "test_supervisor@smartwms.com", "supervisor")
    create_user(db, "test_ventas@smartwms.com", "ventas")
    create_user(db, "test_operario@smartwms.com", "operario")

    # 1. Login roles
    token_super = get_token("test_supervisor@smartwms.com", "admin123")
    token_ventas = get_token("test_ventas@smartwms.com", "admin123")
    token_op = get_token("test_operario@smartwms.com", "admin123")
    
    headers_super = {"Authorization": f"Bearer {token_super}"}
    headers_ventas = {"Authorization": f"Bearer {token_ventas}"}
    headers_op = {"Authorization": f"Bearer {token_op}"}

    # Asegurarnos de que existe un SKU con 0 stock para la prueba
    # Usaremos "SKU-TEST-5"
    db = SessionLocal()
    sku = "SKU-TEST-5"
    prod = db.query(ProductInventory).filter_by(sku=sku).first()
    if not prod:
        prod = ProductInventory(
            sku=sku, product_name="Test Product 5",
            stock_quantity=0, pending_quantity=0,
            unit_price=10.0, reorder_point=5
        )
        db.add(prod)
        db.commit()
    else:
        prod.stock_quantity = 0
        prod.pending_quantity = 0
        db.commit()

    print("\n--- 1. Registrar stock pendiente ---")
    resp = client.post(
        "/api/v1/inventory/receptions",
        json={"sku": sku, "expected_quantity": 50, "notes": "Fase 5"},
        headers=headers_super
    )
    assert resp.status_code == 201
    reception_id = resp.json()["id"]
    print("Recepcion pendiente creada:", resp.json())
    
    # Verificar que el pending_quantity subió a 50
    prod = db.query(ProductInventory).filter_by(sku=sku).first()
    assert prod.pending_quantity == 50
    assert prod.stock_quantity == 0

    print("\n--- 2. Validar rechazo de pedido sin stock disponible ---")
    resp = client.post(
        "/api/v1/work-orders",
        json={
            "order_number": "ORD-TEST-001",
            "items": [{"sku": sku, "quantity": 10}]
        },
        headers=headers_super
    )
    assert resp.status_code == 409
    print("Correcto: Pedido rechazado porque el artículo no tiene stock físico.")
    
    print("\n--- 3. Confirmar la llegada de mercancía ---")
    resp = client.post(
        f"/api/v1/inventory/receptions/{reception_id}/confirm",
        json={"received_quantity": 50, "location": "ZONA-A"},
        headers=headers_super
    )
    assert resp.status_code == 200
    print("Mercancía recibida físicamente!")
    
    # Crear pedido ahora que hay stock
    resp = client.post(
        "/api/v1/work-orders",
        json={
            "order_number": "ORD-TEST-001",
            "items": [{"sku": sku, "quantity": 10}]
        },
        headers=headers_super
    )
    assert resp.status_code == 201
    order = resp.json()
    order_id = order["id"]
    assert order["status"] == "por_asignar"
    print("Pedido creado sin operario en estado 'por_asignar'!")

    print("\n--- 4. Asignación a operario ---")
    # Buscar el id del operario
    op_user = db.query(User).filter_by(email="test_operario@smartwms.com").first()
    resp = client.put(
        f"/api/v1/work-orders/{order_id}/assign",
        json={"assigned_operario_id": op_user.id},
        headers=headers_super
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    print("Pedido asignado al operario y su estado cambió a 'pending'!")

    print("\n--- 5. Despacho desde la app (Android Operario) ---")
    resp = client.post(
        f"/api/v1/work-orders/{order_id}/dispatch",
        json={
            "packages": [
                {"length": 20.0, "width": 10.0, "height": 5.0, "weight": 2.5}
            ],
            "total_weight": 2.5,
            "total_volume": 1000.0
        },
        headers=headers_op
    )
    assert resp.status_code == 200
    dispatched_order = resp.json()
    assert dispatched_order["status"] == "dispatched"
    assert len(dispatched_order["packages"]) == 1
    print("Pedido despachado! Bultos registrados:", dispatched_order["packages"])
    print("Historial Inmutable: Despachado por:", dispatched_order["dispatched_by_email"])
    
    # Verificar stock descontado
    db.refresh(prod)
    assert prod.stock_quantity == 40 # Habían llegado 50, se despacharon 10
    assert prod.pending_quantity == 0
    print("Stock fisico se desconto correctamente: ", prod.stock_quantity)

    print("\n--- Pruebas Fase 5 completadas exitosamente ---")
    
if __name__ == "__main__":
    main()
