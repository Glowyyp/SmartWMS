"""
scripts/test_full_workflow.py — Pruebas de Flujo Completo: Supervisor, Operario y Bot IA

Valida el ciclo operativo de extremo a extremo contra los servidores en ejecución:
1. Login Supervisor y Operario.
2. Supervisor crea un Pedido de Bodega con productos reales.
3. Verificación de cálculo de Stock Reservado y Disponible.
4. Asignación del pedido al Operario.
5. Operario visualiza el pedido asignado en su cola.
6. Consulta al Bot IA (vía puerto 8000 y proxy 8001) sobre ubicación y guía de picking.
7. Operario ejecuta el Despacho registrando bultos (peso y volumen).
8. Descuento atómico del stock físico y verificación de inmutabilidad del despacho.
9. Recepción de mercadería: registro y confirmación con incremento de stock físico.
"""

import sys
import time
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_API = "http://127.0.0.1:8001"
BASE_BOT = "http://127.0.0.1:8000"

def log(msg, ok=True):
    prefix = "  [OK]" if ok else "  [ERROR]"
    print(f"{prefix} {msg}")

def run():
    print("\n" + "="*70)
    print(" INICIANDO PRUEBAS FINALES DE FLUJO COMPLETO: SUPERVISOR Y OPERARIO")
    print("="*70)

    session = requests.Session()

    # -------------------------------------------------------------------------
    # 1. LOGIN DE SUPERVISOR Y OPERARIO
    # -------------------------------------------------------------------------
    print("\n1. Autenticación de Roles en Backend (Puerto 8001)")
    
    # Login Supervisor
    r_sup = session.post(f"{BASE_API}/api/auth/login", data={"username": "supervisor@smartwms.com", "password": "supervisor123"})
    if r_sup.status_code != 200:
        # Intentar con admin123 si la password por defecto fue cambiada
        r_sup = session.post(f"{BASE_API}/api/auth/login", data={"username": "supervisor@smartwms.com", "password": "admin123"})
    assert r_sup.status_code == 200, f"Fallo login supervisor: {r_sup.text}"
    token_sup = r_sup.json()["access_token"]
    role_sup = r_sup.json()["role"]
    assert role_sup == "supervisor"
    log(f"Login Supervisor exitoso ({role_sup}) - Token JWT generado.")

    # Login Operario
    r_op = session.post(f"{BASE_API}/api/auth/login", data={"username": "operario@smartwms.com", "password": "operario123"})
    if r_op.status_code != 200:
        r_op = session.post(f"{BASE_API}/api/auth/login", data={"username": "operario@smartwms.com", "password": "admin123"})
    assert r_op.status_code == 200, f"Fallo login operario: {r_op.text}"
    token_op = r_op.json()["access_token"]
    role_op = r_op.json()["role"]
    assert role_op == "operario"
    log(f"Login Operario exitoso ({role_op}) - Token JWT generado.")

    headers_sup = {"Authorization": f"Bearer {token_sup}"}
    headers_op = {"Authorization": f"Bearer {token_op}"}

    # -------------------------------------------------------------------------
    # 2. CONSULTA DE INVENTARIO Y DISPONIBILIDAD
    # -------------------------------------------------------------------------
    print("\n2. Consulta de Inventario (Supervisor)")
    r_inv = session.get(f"{BASE_API}/api/v1/inventory", headers=headers_sup)
    assert r_inv.status_code == 200, f"Error inventario: {r_inv.text}"
    inventory = r_inv.json()
    assert len(inventory) > 0, "El inventario está vacío"
    
    # Seleccionar un producto con stock disponible
    selected_prod = None
    for p in inventory:
        avail = p.get("available_qty", p.get("stock_quantity", 0))
        if avail >= 5:
            selected_prod = p
            break
            
    assert selected_prod is not None, "No se encontró ningún producto con stock >= 5 para la prueba"
    target_sku = selected_prod["sku"]
    initial_physical = selected_prod["stock_quantity"]
    initial_available = selected_prod["available_qty"]
    log(f"Producto seleccionado: {target_sku} ({selected_prod['product_name']})")
    log(f"Stock físico actual: {initial_physical} | Disponible: {initial_available} (Zona: {selected_prod.get('warehouse_location', 'N/A')})")

    # -------------------------------------------------------------------------
    # 3. SUPERVISOR CREA UN PEDIDO DE BODEGA (WORK ORDER)
    # -------------------------------------------------------------------------
    print("\n3. Creación de Pedido de Bodega (Supervisor)")
    qty_to_order = 2
    r_create = session.post(
        f"{BASE_API}/api/v1/work-orders",
        json={
            "items": [{"sku": target_sku, "quantity": qty_to_order}],
            "assigned_operario_email": None
        },
        headers=headers_sup
    )
    assert r_create.status_code == 201, f"Error al crear pedido: {r_create.text}"
    order_data = r_create.json()
    order_id = order_data["id"]
    order_number = order_data["order_number"]
    assert order_data["status"] == "por_asignar"
    log(f"Pedido creado: {order_number} (ID: {order_id}) en estado '{order_data['status']}'")

    # Verificar que el stock disponible disminuyó por la reserva
    r_inv_check = session.get(f"{BASE_API}/api/v1/inventory", headers=headers_sup)
    updated_p = next(p for p in r_inv_check.json() if p["sku"] == target_sku)
    assert updated_p["stock_quantity"] == initial_physical, "El stock físico no debe cambiar hasta el despacho"
    assert updated_p["available_qty"] == initial_available - qty_to_order, "El stock disponible debió descontar la reserva"
    log(f"Reserva confirmada: Físico={updated_p['stock_quantity']} | Reservado={updated_p['reserved_qty']} | Disponible={updated_p['available_qty']}")

    # -------------------------------------------------------------------------
    # 4. SUPERVISOR ASIGNA EL PEDIDO AL OPERARIO
    # -------------------------------------------------------------------------
    print("\n4. Asignación de Pedido (Supervisor -> Operario)")
    r_assign = session.put(
        f"{BASE_API}/api/v1/work-orders/{order_id}/assign",
        json={"assigned_operario_email": "operario@smartwms.com"},
        headers=headers_sup
    )
    assert r_assign.status_code == 200, f"Error al asignar: {r_assign.text}"
    assigned_data = r_assign.json()
    assert assigned_data["status"] == "pending", f"Estado esperado 'pending', obtenido '{assigned_data['status']}'"
    assert assigned_data["assigned_operario_email"] == "operario@smartwms.com"
    log(f"Pedido {order_number} asignado a operario@smartwms.com (Nuevo estado: '{assigned_data['status']}')")

    # -------------------------------------------------------------------------
    # 5. OPERARIO CONSULTA SU BANDEJA DE PEDIDOS ASIGNADOS
    # -------------------------------------------------------------------------
    print("\n5. Bandeja de Pedidos del Operario (App Operario)")
    r_op_orders = session.get(
        f"{BASE_API}/api/v1/work-orders?status=pending&assigned_to=operario@smartwms.com",
        headers=headers_op
    )
    assert r_op_orders.status_code == 200, f"Error al listar pedidos de operario: {r_op_orders.text}"
    op_orders = r_op_orders.json()
    matching = [o for o in op_orders if o["id"] == order_id]
    assert len(matching) == 1, f"El pedido {order_id} no apareció en la lista del operario"
    log(f"Operario visualiza pedido {order_number} con {len(matching[0]['items'])} SKU(s) para picking.")

    # -------------------------------------------------------------------------
    # 6. ASISTENTE BOT IA: CONSULTAS DE STOCK Y PROCEDIMIENTO
    # -------------------------------------------------------------------------
    print("\n6. Pruebas del Bot IA (Puerto 8000 directo y Puerto 8001 proxy)")

    # Test Bot directo (8000) formato Angular
    r_bot_dir = session.post(
        f"{BASE_BOT}/api/chat",
        json={"text": f"¿Cuál es el stock de {target_sku}?"},
        headers=headers_op
    )
    assert r_bot_dir.status_code == 200, f"Error bot puerto 8000: {r_bot_dir.text}"
    bot_reply_8000 = r_bot_dir.json()["reply"]["text"]
    assert target_sku.lower() in bot_reply_8000.lower() or "stock" in bot_reply_8000.lower()
    log(f"Bot en puerto 8000 respondió correctamente sobre {target_sku}")

    # Test Bot vía Proxy en Backend (8001) formato Android
    r_bot_proxy = session.post(
        f"{BASE_API}/api/chat",
        json={"message": "¿Cómo hago el picking?"},
        headers=headers_op
    )
    assert r_bot_proxy.status_code == 200, f"Error proxy bot puerto 8001: {r_bot_proxy.text}"
    bot_response_proxy = r_bot_proxy.json()["response"]
    assert "picking" in bot_response_proxy.lower() or "qr" in bot_response_proxy.lower()
    log("Proxy de chat en puerto 8001 respondió correctamente con guía de picking.")

    # -------------------------------------------------------------------------
    # 7. OPERARIO EJECUTA EL DESPACHO Y REGISTRO DE BULTOS
    # -------------------------------------------------------------------------
    print("\n7. Despacho y Empaque (Operario)")
    dispatch_payload = {
        "packages": [
            {"length": 25.0, "width": 15.0, "height": 10.0, "weight": 2.2}
        ],
        "total_weight": 2.2,
        "total_volume": 3750.0
    }
    r_disp = session.post(
        f"{BASE_API}/api/v1/work-orders/{order_id}/dispatch",
        json=dispatch_payload,
        headers=headers_op
    )
    assert r_disp.status_code == 200, f"Fallo al despachar pedido: {r_disp.text}"
    disp_data = r_disp.json()
    assert disp_data["status"] == "dispatched"
    assert disp_data["dispatched_by_email"] == "operario@smartwms.com"
    assert disp_data["dispatched_at"] is not None
    assert disp_data["packages_count"] == 1
    log(f"Pedido {order_number} despachado exitosamente por {disp_data['dispatched_by_email']}")
    log(f"Bulto registrado: 25x15x10 cm, 2.2 kg | Despachado el: {disp_data['dispatched_at']}")

    # -------------------------------------------------------------------------
    # 8. VERIFICACIÓN ATÓMICA DE STOCK FÍSICO Y AUDITORÍA
    # -------------------------------------------------------------------------
    print("\n8. Verificación de Descuento de Stock en Inventario")
    r_inv_after = session.get(f"{BASE_API}/api/v1/inventory", headers=headers_sup)
    final_p = next(p for p in r_inv_after.json() if p["sku"] == target_sku)
    expected_physical = initial_physical - qty_to_order
    assert final_p["stock_quantity"] == expected_physical, (
        f"Inconsistencia de stock físico: esperado {expected_physical}, obtenido {final_p['stock_quantity']}"
    )
    log(f"Stock físico descontado correctamente: {initial_physical} -> {final_p['stock_quantity']} uds (-{qty_to_order}).")

    # Intentar despachar nuevamente (debe rechazarse por idempotencia/invariante)
    r_double_disp = session.post(f"{BASE_API}/api/v1/work-orders/{order_id}/dispatch", json={}, headers=headers_op)
    assert r_double_disp.status_code == 409, "Un pedido despachado no debe permitir doble despacho"
    log("Protección contra doble despacho confirmada (HTTP 409 Conflict).")

    # -------------------------------------------------------------------------
    # 9. FLUJO DE RECEPCIONES (RECEPCIÓN Y REABASTECIMIENTO)
    # -------------------------------------------------------------------------
    print("\n9. Recepción de Mercadería (Supervisor/Operario)")
    qty_to_receive = 5
    # Crear recepción pendiente
    r_rec_create = session.post(
        f"{BASE_API}/api/v1/inventory/receptions",
        json={
            "sku": target_sku,
            "expected_quantity": qty_to_receive,
            "notes": "Lote de reposición automatizada"
        },
        headers=headers_sup
    )
    assert r_rec_create.status_code == 201, f"Error crear recepcion: {r_rec_create.text}"
    rec_id = r_rec_create.json()["id"]
    log(f"Recepción #{rec_id} registrada para SKU '{target_sku}' (+{qty_to_receive} uds esperadas)")

    # Confirmar recepción (aumenta stock físico)
    stock_before_rec = final_p["stock_quantity"]
    r_rec_conf = session.post(
        f"{BASE_API}/api/v1/inventory/receptions/{rec_id}/confirm",
        json={"received_quantity": qty_to_receive},
        headers=headers_sup
    )
    assert r_rec_conf.status_code == 200, f"Error confirmar recepcion: {r_rec_conf.text}"
    
    # Comprobar nuevo stock físico
    r_inv_rec = session.get(f"{BASE_API}/api/v1/inventory", headers=headers_sup)
    after_rec_p = next(p for p in r_inv_rec.json() if p["sku"] == target_sku)
    assert after_rec_p["stock_quantity"] == stock_before_rec + qty_to_receive
    log(f"Stock físico reabastecido: {stock_before_rec} -> {after_rec_p['stock_quantity']} uds (+{qty_to_receive}).")

    print("\n" + "="*70)
    print(" ✅ TODOS LOS FLUJOS DE SUPERVISOR Y OPERARIO PASARON EXITOSAMENTE")
    print("="*70)

if __name__ == "__main__":
    run()
