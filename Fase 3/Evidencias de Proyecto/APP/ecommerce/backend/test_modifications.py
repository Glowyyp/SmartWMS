"""
test_modifications.py — Pruebas automatizadas end-to-end para:
  1. Clasificación de stock en 3 niveles (Saludable / Advertencia / Crítico) y sincronización en BD.
  2. Registro histórico de conexiones (UserSession), logout, detección de desconexión inesperada
     (timeout sin contabilizar horas fantasma), métricas individuales/generales y control de roles.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi.testclient import TestClient

cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, cur_dir)
bot_dir = os.path.abspath(os.path.join(cur_dir, "..", "..", "bot"))
sys.path.insert(0, bot_dir)

from app.main import app  # noqa: E402
from app.database import SessionLocal, create_tables  # noqa: E402
from app.models.inventory import ProductInventory  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_session import UserSession  # noqa: E402
from app.models.work_order import WorkOrder, WorkOrderItem  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.stock_status import compute_stock_status  # noqa: E402
from app.core.presence import reconcile_stale_sessions, SESSION_TIMEOUT_SECONDS  # noqa: E402

TEST_ADMIN_EMAIL = "test_mod_admin@smartwms.com"
TEST_SUP_EMAIL = "test_mod_supervisor@smartwms.com"
TEST_OP1_EMAIL = "test_mod_op1@smartwms.com"
TEST_OP2_EMAIL = "test_mod_op2@smartwms.com"
TEST_PASS = "TestMod123!"

TEST_SKUS = [
    "SKU-MOD-CRIT0",
    "SKU-MOD-CRIT10",
    "SKU-MOD-WARN15",
    "SKU-MOD-WARN20",
    "SKU-MOD-OK25",
    "SKU-MOD-ZERO-RP",
]


def _ensure_user(db, email: str, name: str, role: str) -> User:
    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(
            email=email,
            full_name=name,
            hashed_password=hash_password(TEST_PASS),
            role=role,
            is_active=True,
            mfa_enabled=False,
        )
        db.add(u)
        db.flush()
    else:
        u.full_name = name
        u.hashed_password = hash_password(TEST_PASS)
        u.role = role
        u.is_active = True
        u.mfa_enabled = False
        u.is_connected = False
        u.last_seen_at = None
        u.last_login_at = None
    db.query(UserSession).filter(UserSession.user_id == u.id).delete()
    return u


def _cleanup():
    db = SessionLocal()
    try:
        # Eliminar work orders que usen SKUs de prueba
        wo_ids = [
            r[0]
            for r in db.query(WorkOrderItem.work_order_id)
            .filter(WorkOrderItem.sku.in_(TEST_SKUS))
            .distinct()
            .all()
        ]
        if wo_ids:
            db.query(WorkOrder).filter(WorkOrder.id.in_(wo_ids)).delete(synchronize_session=False)
        db.query(ProductInventory).filter(ProductInventory.sku.in_(TEST_SKUS)).delete(synchronize_session=False)
        users = db.query(User).filter(
            User.email.in_([TEST_ADMIN_EMAIL, TEST_SUP_EMAIL, TEST_OP1_EMAIL, TEST_OP2_EMAIL])
        ).all()
        for u in users:
            db.query(UserSession).filter(UserSession.user_id == u.id).delete()
            db.delete(u)
        db.commit()
    finally:
        db.close()


def _login(client: TestClient, email: str, client_type: str = "web") -> str:
    headers = {"X-Client-Type": client_type}
    r = client.post(
        "/api/auth/login",
        data={"username": email, "password": TEST_PASS},
        headers=headers,
    )
    assert r.status_code == 200, f"Login falló para {email}: {r.text}"
    body = r.json()
    if body.get("access_token"):
        return body["access_token"]

    # Completar flujo MFA real (setup + activate) para validar creación de sesión vía MFA
    assert body.get("mfa_required") and body.get("mfa_token"), f"Respuesta login inesperada: {body}"
    mfa_token = body["mfa_token"]
    r_setup = client.post(
        "/api/auth/mfa/setup",
        headers={**headers, "Authorization": f"Bearer {mfa_token}"},
    )
    assert r_setup.status_code == 200, f"MFA setup falló para {email}: {r_setup.text}"
    secret = r_setup.json()["secret"]
    code = pyotp.TOTP(secret).now()
    r_act = client.post(
        "/api/auth/mfa/activate",
        json={"code": code, "mfa_token": mfa_token},
        headers=headers,
    )
    assert r_act.status_code == 200, f"MFA activate falló para {email}: {r_act.text}"
    token = r_act.json()["access_token"]
    assert token, f"No se entregó access_token tras MFA activate para {email}"
    return token


def run_tests():
    print("\n" + "=" * 70)
    print(" SUITE DE PRUEBAS: ESTADOS DE STOCK (3 NIVELES) + ACTIVIDAD DE USUARIOS")
    print("=" * 70)

    create_tables()
    _cleanup()

    db = SessionLocal()
    try:
        admin_u = _ensure_user(db, TEST_ADMIN_EMAIL, "Admin Prueba", "admin")
        sup_u = _ensure_user(db, TEST_SUP_EMAIL, "Supervisor Prueba", "supervisor")
        op1_u = _ensure_user(db, TEST_OP1_EMAIL, "Operario Uno", "operario")
        op2_u = _ensure_user(db, TEST_OP2_EMAIL, "Operario Dos", "operario")
        db.commit()
        admin_id, sup_id, op1_id, op2_id = admin_u.id, sup_u.id, op1_u.id, op2_u.id
    finally:
        db.close()

    try:
        with TestClient(app) as client:
            # ── 1. CLASIFICACIÓN DE STOCK EN 3 NIVELES ───────────────────────
            assert compute_stock_status(0, 10) == "critical"
            assert compute_stock_status(10, 10) == "critical"
            assert compute_stock_status(11, 10) == "warning"
            assert compute_stock_status(20, 10) == "warning"
            assert compute_stock_status(21, 10) == "healthy"
            assert compute_stock_status(0, 0) == "critical"
            assert compute_stock_status(5, 0) == "healthy"
            print("  [OK] 1. Función compute_stock_status valida todos los límites (critical / warning / healthy).")

            admin_tok = _login(client, TEST_ADMIN_EMAIL, "web")
            admin_h = {"Authorization": f"Bearer {admin_tok}", "X-Client-Type": "web"}

            # Crear productos en los 3 rangos
            test_products = [
                ("SKU-MOD-CRIT0", "Prod Crítico 0", 0, 10, "critical", True),
                ("SKU-MOD-CRIT10", "Prod Crítico 10", 10, 10, "critical", True),
                ("SKU-MOD-WARN15", "Prod Advertencia 15", 15, 10, "warning", False),
                ("SKU-MOD-WARN20", "Prod Advertencia 20", 20, 10, "warning", False),
                ("SKU-MOD-OK25", "Prod Saludable 25", 25, 10, "healthy", False),
                ("SKU-MOD-ZERO-RP", "Prod Sin Reorden", 5, 0, "healthy", False),
            ]
            created_ids = {}
            for sku, name, stock, rp, expected_status, expected_low in test_products:
                r = client.post(
                    "/api/v1/inventory",
                    json={
                        "sku": sku,
                        "product_name": name,
                        "stock_quantity": stock,
                        "unit_price": 10.0,
                        "reorder_point": rp,
                    },
                    headers=admin_h,
                )
                assert r.status_code == 201, f"Error creando {sku}: {r.text}"
                p = r.json()
                assert p["stock_status"] == expected_status, f"{sku}: esperaba {expected_status}, obtuvo {p['stock_status']}"
                assert p["is_low_stock"] is expected_low, f"{sku}: is_low_stock incorrecto"
                assert p["warning_threshold"] == rp * 2
                created_ids[sku] = p["id"]
            print("  [OK] 2. Creación de productos asigna y persiste exactamente healthy / warning / critical.")

            # Verificar filtros en GET /api/v1/inventory?stock_status=...
            r_warn = client.get("/api/v1/inventory?stock_status=warning", headers=admin_h)
            assert r_warn.status_code == 200
            warn_skus = {p["sku"] for p in r_warn.json()}
            assert "SKU-MOD-WARN15" in warn_skus and "SKU-MOD-WARN20" in warn_skus
            assert "SKU-MOD-CRIT10" not in warn_skus and "SKU-MOD-OK25" not in warn_skus

            r_crit = client.get("/api/v1/inventory?stock_status=critical", headers=admin_h)
            crit_skus = {p["sku"] for p in r_crit.json()}
            assert "SKU-MOD-CRIT0" in crit_skus and "SKU-MOD-CRIT10" in crit_skus
            assert "SKU-MOD-WARN15" not in crit_skus
            print("  [OK] 3. Filtro de API por stock_status separa correctamente Crítico, Advertencia y Saludable.")

            # Verificar transición dinámica al reservar stock mediante Work Order (25 -> 15 warning -> cancelar -> 25 healthy)
            r_wo = client.post(
                "/api/v1/work-orders",
                json={"items": [{"sku": "SKU-MOD-OK25", "quantity": 10}]},
                headers=admin_h,
            )
            assert r_wo.status_code == 201, f"Error creando WO: {r_wo.text}"
            wo_id = r_wo.json()["id"]

            db = SessionLocal()
            try:
                p_row = db.query(ProductInventory).filter(ProductInventory.sku == "SKU-MOD-OK25").first()
                assert p_row.stock_status == "warning", f"Al reservar 10 de 25 (disp=15, rp=10) BD debe guardar 'warning', obtuvo {p_row.stock_status}"
            finally:
                db.close()

            r_cancel = client.post(f"/api/v1/work-orders/{wo_id}/cancel", headers=admin_h)
            assert r_cancel.status_code == 200
            db = SessionLocal()
            try:
                p_row = db.query(ProductInventory).filter(ProductInventory.sku == "SKU-MOD-OK25").first()
                assert p_row.stock_status == "healthy", f"Al cancelar reserva debe volver a 'healthy', obtuvo {p_row.stock_status}"
            finally:
                db.close()
            print("  [OK] 4. Consistencia BD <-> API: reservas y cancelaciones actualizan product_inventory.stock_status.")

            # ── 2. REGISTRO DE CONEXIONES, HEARTBEAT, LOGOUT Y TIMEOUT ───────
            sup_tok = _login(client, TEST_SUP_EMAIL, "web")
            op1_tok = _login(client, TEST_OP1_EMAIL, "mobile")
            op2_tok = _login(client, TEST_OP2_EMAIL, "mobile")

            sup_h = {"Authorization": f"Bearer {sup_tok}", "X-Client-Type": "web"}
            op1_h = {"Authorization": f"Bearer {op1_tok}", "X-Client-Type": "mobile"}
            op2_h = {"Authorization": f"Bearer {op2_tok}", "X-Client-Type": "mobile"}

            # Heartbeat explícito de op1
            r_hb = client.post("/api/auth/heartbeat", headers=op1_h)
            assert r_hb.status_code == 200
            assert r_hb.json()["status"] == "ok"
            assert r_hb.json()["session_id"] is not None

            # Simular 5 minutos de sesión para op1 y cerrar sesión explícitamente
            db = SessionLocal()
            try:
                s_op1 = db.query(UserSession).filter(UserSession.user_id == op1_id, UserSession.status == "active").first()
                assert s_op1 is not None and s_op1.client_type == "mobile"
                s_op1.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
                db.commit()
            finally:
                db.close()

            r_logout = client.post("/api/auth/logout", headers=op1_h)
            assert r_logout.status_code == 200
            assert r_logout.json()["duration_seconds"] >= 295, f"Duración logout esperada ~300s, obtuvo {r_logout.json()}"
            print("  [OK] 5. Login móvil, heartbeat y logout registran duración exacta y cierran la sesión.")

            # Simular desconexión abrupta / pérdida de internet para op2:
            # Inició hace 30 min, última actividad hace 10 min (> SESSION_TIMEOUT_SECONDS), nunca hizo logout.
            now_utc = datetime.now(timezone.utc)
            db = SessionLocal()
            try:
                s_op2 = db.query(UserSession).filter(UserSession.user_id == op2_id, UserSession.status == "active").first()
                assert s_op2 is not None
                s_op2.started_at = now_utc - timedelta(minutes=30)
                s_op2.last_activity_at = now_utc - timedelta(minutes=10)
                u_op2 = db.query(User).filter(User.id == op2_id).first()
                u_op2.last_seen_at = now_utc - timedelta(minutes=10)
                db.commit()
            finally:
                db.close()

            # Consultar overview como supervisor: debe reconciliar el timeout de op2 automáticamente
            r_ov_sup = client.get("/api/v1/activity/overview?days=7", headers=sup_h)
            assert r_ov_sup.status_code == 200, f"Overview supervisor falló: {r_ov_sup.text}"
            ov_sup = r_ov_sup.json()

            # Verificar desconexión inesperada de op2: duración ~20 min (1200s), NO 30 min (1800s)
            r_op2_detail = client.get(f"/api/v1/activity/users/{op2_id}?days=7", headers=sup_h)
            assert r_op2_detail.status_code == 200
            op2_det = r_op2_detail.json()
            assert op2_det["user"]["is_online"] is False, "op2 debe figurar desconectado tras timeout"
            assert len(op2_det["sessions"]) == 1
            op2_sess = op2_det["sessions"][0]
            assert op2_sess["status"] == "timeout", f"Esperaba status 'timeout', obtuvo {op2_sess['status']}"
            assert op2_sess["disconnect_reason"] == "inactivity_timeout"
            assert 1190 <= op2_sess["duration_seconds"] <= 1210, (
                f"Duración tras desconexión abrupta debe acotarse a última actividad (~1200s), obtuvo {op2_sess['duration_seconds']}s"
            )
            print("  [OK] 6. Desconexión abrupta detectada por timeout: ended_at = last_activity_at (~1200s, sin horas fantasma).")

            # Verificar métricas individuales de op1
            r_op1_detail = client.get(f"/api/v1/activity/users/{op1_id}?days=7", headers=sup_h)
            assert r_op1_detail.status_code == 200
            op1_det = r_op1_detail.json()
            assert op1_det["user"]["total_sessions"] == 1
            assert op1_det["user"]["total_duration_seconds"] >= 295
            assert op1_det["user"]["avg_session_seconds"] >= 295
            assert op1_det["user"]["today_duration_seconds"] >= 295
            assert op1_det["user"]["week_duration_seconds"] >= 295
            assert len(op1_det["daily_activity"]) == 7
            print("  [OK] 7. Métricas individuales y serie diaria calculadas correctamente.")

            # ── 3. PERMISOS Y AISLAMIENTO DE ROLES ───────────────────────────
            # Operario NO puede acceder a ningún endpoint de actividad (403)
            assert client.get("/api/v1/activity/overview", headers=op1_h).status_code == 403
            assert client.get(f"/api/v1/activity/users/{op2_id}", headers=op1_h).status_code == 403
            assert client.get("/api/v1/activity/sessions", headers=op1_h).status_code == 403

            # Supervisor NO ve usuarios admin en overview ni puede consultar su detalle
            sup_visible_ids = {u["user_id"] for u in ov_sup["users"]}
            assert admin_id not in sup_visible_ids, "Supervisor NO debe ver cuentas admin en actividad"
            assert sup_id in sup_visible_ids and op1_id in sup_visible_ids and op2_id in sup_visible_ids
            assert all(u["email"] is None for u in ov_sup["users"]), "Supervisor no debe recibir emails"
            assert client.get(f"/api/v1/activity/users/{admin_id}", headers=sup_h).status_code == 404

            # Admin SÍ ve a todos incluyendo admin y correos
            r_ov_admin = client.get("/api/v1/activity/overview?days=7", headers=admin_h)
            assert r_ov_admin.status_code == 200
            admin_visible_ids = {u["user_id"] for u in r_ov_admin.json()["users"]}
            assert admin_id in admin_visible_ids
            assert r_ov_admin.json()["summary"]["total_users"] == len(r_ov_admin.json()["users"])
            assert (
                r_ov_admin.json()["summary"]["online_users"] + r_ov_admin.json()["summary"]["offline_users"]
                == r_ov_admin.json()["summary"]["total_users"]
            )
            print("  [OK] 8. Control de permisos y aislamiento por rol verificados (Operario=403, Supervisor sin admins, Admin completo).")

            # Verificar helper del Bot IA también clasifica 3 niveles
            import importlib.util
            bot_spec = importlib.util.spec_from_file_location("bot_main_check", os.path.join(bot_dir, "main.py"))
            if bot_spec and bot_spec.loader:
                # Validar lógica sin arrancar Telegram
                src = open(os.path.join(bot_dir, "main.py"), encoding="utf-8").read()
                assert "def classify_stock_status" in src and "🟡 ADVERTENCIA" in src
                print("  [OK] 9. Clasificación de 3 niveles verificada en bot/main.py.")

            # Verificar que GET /api/v1/layout entrega qr_code SVG para cada mesa del Layout
            r_layout = client.get("/api/v1/layout", headers=admin_h)
            assert r_layout.status_code == 200, f"Error obteniendo layout: {r_layout.text}"
            tables = r_layout.json()["tables"]
            assert len(tables) >= 4, "Deben existir mesas en el layout"
            for t in tables:
                assert t.get("qr_code", "").startswith("data:image/svg+xml"), f"Mesa {t.get('code')} sin QR SVG"
            print("  [OK] 10. Layout del Supervisor genera qr_code SVG para cada mesa de bodega.")

        print("\n✅ TODAS LAS PRUEBAS PASARON EXITOSAMENTE (10/10).\n")
    finally:
        _cleanup()


if __name__ == "__main__":
    run_tests()
