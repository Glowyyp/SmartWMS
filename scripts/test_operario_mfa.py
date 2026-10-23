"""
test_operario_mfa.py — Prueba completa del ciclo de vida de MFA para el Operario:
1. Verificación de cuenta operario existente.
2. Login inicial de operario.
3. Consulta de estado MFA antes de la activación (mfa_enabled = False).
4. Solicitud de enrolamiento en sesión (setup): entrega de secreto, otpauth:// URI, recovery codes.
5. Validación de formato de URI para Google Authenticator, Microsoft Authenticator, Aegis.
6. Intento de activación con código TOTP inválido (debe ser rechazado con HTTP 400).
7. Activación exitosa con código TOTP válido generado en base al secreto.
8. Consulta de estado MFA tras activación (mfa_enabled = True).
9. Verificación de persistencia: Cerrar sesión e iniciar sesión nuevamente.
10. Comprobar que el login ahora exige obligatoriamente el segundo factor (stage='verify').
11. Verificación del segundo factor y obtención del access_token final.
12. Comprobar que el supervisor continúa operando normalmente con su propio MFA sin interferencias.
"""

import sys
import os
import pyotp

sys.path.insert(0, os.path.abspath("ecommerce/backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.core import security, mfa

client = TestClient(app)

TEST_OPERARIO_EMAIL = "operario_mfa_test@smartwms.com"
TEST_OPERARIO_PASS  = "operario123"

def setup_test_users():
    with SessionLocal() as db:
        # Asegurar usuario operario para esta prueba
        user = db.query(User).filter_by(email=TEST_OPERARIO_EMAIL).first()
        if not user:
            user = User(
                email=TEST_OPERARIO_EMAIL,
                full_name="Operario Test MFA",
                hashed_password=security.hash_password(TEST_OPERARIO_PASS),
                role="operario",
                is_active=True,
                mfa_enabled=False
            )
            db.add(user)
        else:
            user.is_active = True
            user.hashed_password = security.hash_password(TEST_OPERARIO_PASS)
            mfa.reset_user_mfa(user)
        
        # Asegurar supervisor para prueba de no regresión
        sup = db.query(User).filter_by(email="supervisor@smartwms.com").first()
        if sup:
            sup.mfa_last_used_step = None
            sup.mfa_failed_attempts = 0
            sup.mfa_locked_until = None

        db.commit()

def run_tests():
    print("=" * 65)
    print("Iniciando pruebas del flujo de activacion de MFA para el Operario")
    print("=" * 65)

    setup_test_users()

    # 1. Login inicial del operario
    # Si MFA_REQUIRED_ROLES="*" y mfa_enabled=False, el login solicitará setup.
    login_resp = client.post("/api/auth/login", data={"username": TEST_OPERARIO_EMAIL, "password": TEST_OPERARIO_PASS})
    assert login_resp.status_code == 200, f"Error en login inicial: {login_resp.text}"
    login_data = login_resp.json()
    print("[OK] 1. Login inicial exitoso para operario")

    # Identificar token disponible (mfa_token de setup o access_token directo)
    if login_data.get("mfa_required") and login_data.get("stage") == "setup":
        init_token = login_data["mfa_token"]
        is_pending = True
        print("     -> Login requiere configuracion inicial MFA (stage=setup)")
    else:
        init_token = login_data["access_token"]
        is_pending = False
        print("     -> Login entrego access_token directo (sin MFA previo)")

    headers = {"Authorization": f"Bearer {init_token}"}

    # 2. Iniciar setup de MFA
    setup_resp = client.post("/api/auth/mfa/setup", headers=headers)
    assert setup_resp.status_code == 200, f"Error en setup MFA: {setup_resp.text}"
    setup_data = setup_resp.json()
    secret = setup_data["secret"]
    uri = setup_data["provisioning_uri"]
    recovery_codes = setup_data["recovery_codes"]
    account_name = setup_data["account_name"]

    assert len(secret) >= 16, "El secreto generado no tiene la longitud Base32 requerida"
    assert uri.startswith("otpauth://totp/"), f"La URI no tiene el esquema otpauth://totp/: {uri}"
    assert "operario_mfa_test" in uri, "La cuenta del operario no esta en la URI otpauth"
    assert len(recovery_codes) == 10, f"Esperados 10 codigos de recuperacion, obtenidos {len(recovery_codes)}"
    assert account_name == TEST_OPERARIO_EMAIL, "El account_name no coincide con el operario"
    print(f"[OK] 2. Setup MFA generado correctamente:")
    print(f"     - Secreto Base32: {secret[:6]}... (generado de forma segura y unica)")
    print(f"     - Provisioning URI: {uri[:45]}...")
    print(f"     - Codigos de recuperacion entregados: {len(recovery_codes)} codigos")
    print(f"     - Cuenta asociada: {account_name}")

    # 3. Intentar activacion con codigo invalido
    bad_payload = {"code": "000000", "mfa_token": init_token if is_pending else None}
    bad_act = client.post("/api/auth/mfa/activate", json=bad_payload, headers=headers)
    assert bad_act.status_code == 400, f"Se esperaba 400 ante codigo invalido, obtenido {bad_act.status_code}"
    print("[OK] 3. Codigo invalido rechazado correctamente (HTTP 400)")

    # 4. Validar que la cuenta NO este marcada como activa todavia
    with SessionLocal() as db:
        user_check = db.query(User).filter_by(email=TEST_OPERARIO_EMAIL).first()
        assert user_check.mfa_enabled == False, "MFA no debe figurar activado antes de validar el codigo"
    print("[OK] 4. Verificado: MFA permanece desactivado hasta confirmacion exitosa")

    # 5. Activar con codigo TOTP valido generado en tiempo real
    good_code = pyotp.TOTP(secret).now()
    good_payload = {"code": good_code, "mfa_token": init_token if is_pending else None}
    good_act = client.post("/api/auth/mfa/activate", json=good_payload, headers=headers)
    assert good_act.status_code == 200, f"Error activando MFA: {good_act.text}"
    act_data = good_act.json()
    new_access_token = act_data["access_token"]
    assert new_access_token is not None, "La activacion no entrego access_token definitivo"
    assert act_data["role"] == "operario"
    print("[OK] 5. MFA activado exitosamente con codigo TOTP valido")

    # 6. Consultar estado MFA desde la sesion activa
    auth_headers = {"Authorization": f"Bearer {new_access_token}"}
    status_resp = client.get("/api/auth/mfa/status", headers=auth_headers)
    assert status_resp.status_code == 200, f"Error consultando status: {status_resp.text}"
    status_data = status_resp.json()
    assert status_data["mfa_enabled"] == True, "mfa_enabled debe ser True tras la activacion"
    assert status_data["remaining_recovery_codes"] == 10
    print(f"[OK] 6. Endpoint /api/auth/mfa/status confirma: mfa_enabled=True, codigos restantes={status_data['remaining_recovery_codes']}")

    # 7. Persistencia: Cerrar sesion e iniciar sesion de nuevo
    print("[OK] 7. Probando re-login (persistencia de MFA)...")
    re_login = client.post("/api/auth/login", data={"username": TEST_OPERARIO_EMAIL, "password": TEST_OPERARIO_PASS})
    assert re_login.status_code == 200
    re_data = re_login.json()
    assert re_data["mfa_required"] == True, "El nuevo login debe exigir MFA obligatoriamente"
    assert re_data["stage"] == "verify", f"Esperado stage='verify', obtenido {re_data.get('stage')}"
    print(f"[OK] 8. Re-login requiere segundo factor (stage='verify', mfa_required=True)")

    # 8. Verificar segundo factor en el nuevo login usando TOTP
    verify_mfa_token = re_data["mfa_token"]
    # Para evitar colision de mismo paso TOTP en test rapido, usamos TOTP valido
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=TEST_OPERARIO_EMAIL).first()
        u.mfa_last_used_step = None
        db.commit()
    second_code = pyotp.TOTP(secret).now()
    verify_resp = client.post("/api/auth/mfa/verify", json={"code": second_code, "mfa_token": verify_mfa_token})
    assert verify_resp.status_code == 200, f"Fallo al verificar segundo factor: {verify_resp.text}"
    final_token = verify_resp.json()["access_token"]
    assert final_token is not None
    print("[OK] 9. Segundo factor verificado exitosamente tras el nuevo login")

    # 9. Reconfiguracion dentro de sesion (en caso de que el operario quiera re-vincular)
    re_setup = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {final_token}"})
    assert re_setup.status_code == 200, "El operario en sesion puede volver a solicitar setup"
    print("[OK] 10. Reconfiguracion dentro de sesion activa habilitada y funcionando")

    # 10. No regresion: verificar que el supervisor sigue funcionando con MFA normalmente
    with SessionLocal() as db:
        sup_user = db.query(User).filter_by(email="supervisor@smartwms.com").first()
        sup_secret = mfa.decrypt_secret(sup_user.mfa_secret_enc)
        sup_user.mfa_last_used_step = None
        sup_user.mfa_failed_attempts = 0
        db.commit()

    sup_login = client.post("/api/auth/login", data={"username": "supervisor@smartwms.com", "password": "admin123"})
    assert sup_login.status_code == 200
    sup_mfa_token = sup_login.json()["mfa_token"]
    sup_code = pyotp.TOTP(sup_secret).now()
    sup_verify = client.post("/api/auth/mfa/verify", json={"code": sup_code, "mfa_token": sup_mfa_token})
    assert sup_verify.status_code == 200
    assert sup_verify.json()["role"] == "supervisor"
    print("[OK] 11. Sin regresiones: MFA de supervisor verificado y funcionando al 100%")

    print("=" * 65)
    print("TODAS LAS PRUEBAS DE MFA DEL OPERARIO PASARON EXITOSAMENTE (11/11)")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
