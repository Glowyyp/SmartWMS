"""
test_feature_enhancements.py — Prueba integral de:
1. Cancelación de pedidos (supervisor) y liberación de reserva de stock.
2. Restricciones de cancelación (pedidos despachados o ya cancelados).
3. Transiciones manuales de estado (supervisor) y persistencia en DB.
4. Historial de estados con identificación de usuario y timestamp.
5. Validación de códigos y flujo operario.
"""

import sys
import os
import sqlite3
from datetime import datetime

# Añadir backend al path
sys.path.insert(0, os.path.abspath("ecommerce/backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.database import engine, get_db
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderStatusHistory
from app.models.inventory import ProductInventory
from app.models.user import User

client = TestClient(app)

def login_user(email, password):
    resp = client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, f"Login falló para {email}: {resp.text}"
    data = resp.json()
    if data.get("access_token"):
        return data["access_token"]
    if data.get("mfa_required"):
        mfa_token = data["mfa_token"]
        stage = data.get("stage")
        import pyotp
        if stage == "setup":
            s_resp = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {mfa_token}"})
            secret = s_resp.json()["secret"]
            code = pyotp.TOTP(secret).now()
            a_resp = client.post("/api/auth/mfa/activate", json={"code": code}, headers={"Authorization": f"Bearer {mfa_token}"})
            return a_resp.json()["access_token"]
        elif stage == "verify":
            from app.core import mfa
            from app.database import SessionLocal
            with SessionLocal() as db:
                user = db.query(User).filter(User.email == email).first()
                user.mfa_last_used_step = None
                user.mfa_failed_attempts = 0
                user.mfa_locked_until = None
                db.commit()
                secret = mfa.decrypt_secret(user.mfa_secret_enc)
                code = pyotp.TOTP(secret).now()
            v_resp = client.post("/api/auth/mfa/verify", json={"code": code}, headers={"Authorization": f"Bearer {mfa_token}"})
            assert v_resp.status_code == 200, f"MFA verify falló para {email}: {v_resp.text}"
            return v_resp.json()["access_token"]
    raise Exception(f"No access token for {email}: {data}")

def run_tests():
    print("=" * 60)
    print("Iniciando pruebas integrales de gestión de pedidos y estados")
    print("=" * 60)

    # 1. Login Supervisor
    sup_token = login_user("supervisor@smartwms.com", "admin123")
    sup_headers = {"Authorization": f"Bearer {sup_token}"}
    print("[OK] 1. Login supervisor exitoso")

    # 2. Login Operario
    op_token = login_user("operario@smartwms.com", "admin123")
    op_headers = {"Authorization": f"Bearer {op_token}"}
    print("[OK] 2. Login operario exitoso")

    # 3. Consultar stock disponible de un SKU de prueba
    inv_res = client.get("/api/v1/inventory", headers=sup_headers)
    assert inv_res.status_code == 200
    products = inv_res.json()
    test_prod = next((p for p in products if p["stock_quantity"] >= 10), products[0])
    test_sku = test_prod["sku"]
    initial_avail = test_prod["available_qty"]
    initial_reserved = test_prod["reserved_qty"]
    print(f"[OK] 3. SKU de prueba: {test_sku} | Stock físico={test_prod['stock_quantity']} | Reservado={initial_reserved} | Disp={initial_avail}")

    # 4. Crear nuevo pedido (Work Order)
    create_payload = {
        "items": [{"sku": test_sku, "quantity": 2}],
        "assigned_operario_email": "operario@smartwms.com"
    }
    create_res = client.post("/api/v1/work-orders", json=create_payload, headers=sup_headers)
    assert create_res.status_code == 201, f"Creación de pedido falló: {create_res.text}"
    wo = create_res.json()
    wo_id = wo["id"]
    wo_num = wo["order_number"]
    assert wo["status"] == "pending", f"Esperado 'pending', obtenido '{wo['status']}'"
    print(f"[OK] 4. Pedido creado: {wo_num} (ID: {wo_id}) en estado 'pending'")

    # Verificar que el stock se reservó
    inv_after_create = client.get("/api/v1/inventory", headers=sup_headers).json()
    prod_after = next(p for p in inv_after_create if p["sku"] == test_sku)
    assert prod_after["reserved_qty"] == initial_reserved + 2, "La reserva de stock no aumentó"
    print(f"[OK] 5. Reserva de stock confirmada: aumentó a {prod_after['reserved_qty']} (+2 uds)")

    # 5. Probar transiciones de estado manuales del supervisor
    # Transition 1: pending -> in_preparation
    put_res1 = client.put(f"/api/v1/work-orders/{wo_id}", json={"status": "in_preparation"}, headers=sup_headers)
    assert put_res1.status_code == 200, f"Error cambiando a in_preparation: {put_res1.text}"
    assert put_res1.json()["status"] == "in_preparation"
    print("[OK] 6. Transición a 'in_preparation' exitosa")

    # Transition 2: in_preparation -> in_progress
    put_res2 = client.put(f"/api/v1/work-orders/{wo_id}", json={"status": "in_progress"}, headers=sup_headers)
    assert put_res2.status_code == 200, f"Error cambiando a in_progress: {put_res2.text}"
    assert put_res2.json()["status"] == "in_progress"
    print("[OK] 7. Transición a 'in_progress' exitosa")

    # Transition 3: in_progress -> waiting_stock
    put_res3 = client.put(f"/api/v1/work-orders/{wo_id}", json={"status": "waiting_stock"}, headers=sup_headers)
    assert put_res3.status_code == 200, f"Error cambiando a waiting_stock: {put_res3.text}"
    assert put_res3.json()["status"] == "waiting_stock"
    print("[OK] 8. Transición a 'waiting_stock' exitosa")

    # 6. Cancelación de pedido desde el supervisor (incluso en preparación/espera)
    cancel_res = client.post(f"/api/v1/work-orders/{wo_id}/cancel", headers=sup_headers)
    assert cancel_res.status_code == 200, f"Error cancelando pedido: {cancel_res.text}"
    cancelled_wo = cancel_res.json()
    assert cancelled_wo["status"] == "cancelled"
    assert cancelled_wo["cancelled_by_email"] == "supervisor@smartwms.com"
    assert cancelled_wo["cancelled_at"] is not None
    print(f"[OK] 9. Cancelación de pedido {wo_num} exitosa (cancelled_by={cancelled_wo['cancelled_by_email']})")

    # 7. Verificar que la reserva de stock fue liberada inmediatamente
    inv_after_cancel = client.get("/api/v1/inventory", headers=sup_headers).json()
    prod_cancelled = next(p for p in inv_after_cancel if p["sku"] == test_sku)
    assert prod_cancelled["reserved_qty"] == initial_reserved, "La reserva de stock no se liberó tras la cancelación"
    print(f"[OK] 10. Liberación de stock confirmada: reservado volvió a {prod_cancelled['reserved_qty']}")

    # 8. Regla de negocio: No se puede reactivar un pedido cancelado
    reactivate_res = client.put(f"/api/v1/work-orders/{wo_id}", json={"status": "pending"}, headers=sup_headers)
    assert reactivate_res.status_code == 409, f"Esperado 409 Conflict al reactivar pedido cancelado, obtenido {reactivate_res.status_code}"
    print("[OK] 11. Regla protegida: reactivación de pedido cancelado rechazada con HTTP 409 Conflict")

    # 9. Regla de negocio: No se puede cancelar un pedido ya cancelado
    double_cancel_res = client.post(f"/api/v1/work-orders/{wo_id}/cancel", headers=sup_headers)
    assert double_cancel_res.status_code == 409, f"Esperado 409 al re-cancelar, obtenido {double_cancel_res.status_code}"
    print("[OK] 12. Regla protegida: re-cancelación de pedido cancelado rechazada con HTTP 409 Conflict")

    # 10. Probar historial de estados auditado
    hist_res = client.get(f"/api/v1/work-orders/{wo_id}/history", headers=sup_headers)
    assert hist_res.status_code == 200, f"Error obteniendo historial: {hist_res.text}"
    history = hist_res.json()
    assert len(history) >= 4, f"Esperado al menos 4 registros de historial, obtenidos {len(history)}"
    print(f"[OK] 13. Historial de estados verificado ({len(history)} transiciones registradas):")
    for h in history:
        print(f"    - [{h['created_at'][:19]}] {h['from_status']} -> {h['to_status']} | Por: {h['changed_by_email']} | Nota: {h['notes']}")

    # 11. Probar flujo de despacho y protección de cancelación en despacho
    create_dispatch_wo = client.post("/api/v1/work-orders", json={
        "items": [{"sku": test_sku, "quantity": 1}],
        "assigned_operario_email": "operario@smartwms.com"
    }, headers=sup_headers).json()
    disp_wo_id = create_dispatch_wo["id"]
    disp_wo_num = create_dispatch_wo["order_number"]

    # Despachar como operario
    disp_res = client.post(f"/api/v1/work-orders/{disp_wo_id}/dispatch", json={
        "packages": [{"length": 20, "width": 15, "height": 10, "weight": 1.5}]
    }, headers=op_headers)
    assert disp_res.status_code == 200, f"Despacho falló: {disp_res.text}"
    assert disp_res.json()["status"] == "dispatched"
    print(f"[OK] 14. Pedido {disp_wo_num} despachado exitosamente por operario")

    # Regla de negocio: No se puede cancelar un pedido ya despachado
    cancel_dispatched = client.post(f"/api/v1/work-orders/{disp_wo_id}/cancel", headers=sup_headers)
    assert cancel_dispatched.status_code == 409, f"Esperado 409 al cancelar pedido despachado, obtenido {cancel_dispatched.status_code}"
    print("[OK] 15. Regla protegida: cancelación de pedido despachado rechazada con HTTP 409 Conflict")

    print("=" * 60)
    print("TODAS LAS PRUEBAS (15/15) PASARON EXITOSAMENTE.")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
